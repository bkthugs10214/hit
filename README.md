# precog-baseline-miner

A simple, valid, improvable baseline miner for the
[Coin Metrics Precog subnet](https://github.com/coinmetrics/precog) on Bittensor.

The miner:
- Fetches 1-minute OHLCV candles from Binance (public API, no key required)
- Produces a **point forecast** using momentum + heavy shrinkage
- Produces an **interval forecast** using realized volatility
- Handles all three Precog assets: BTC, ETH, TAO
- Logs every forecast to `~/.precog_baseline/forecasts.jsonl`
- Back-fills realized outcomes for offline evaluation

---

## Project layout

```
precog-baseline-miner/
├── INTERFACE_NOTES.md     Precog synapse/protocol reference
├── .env.example           Environment variable template
├── pyproject.toml         Build config
├── setup.py               Package mapping (src/ → precog_baseline_miner)
├── deploy.sh              One-command setup script
├── src/
│   ├── config.py          Reads env vars (shrinkage, log dir, …)
│   ├── main.py            Standalone smoke test (no Bittensor required)
│   ├── data/
│   │   ├── binance_client.py   Binance REST API: fetch 1-min candles
│   │   └── candles.py          DataFrame helpers
│   ├── features/
│   │   ├── returns.py          5-min / 15-min momentum returns
│   │   └── volatility.py       Realized vol → hourly vol estimate
│   ├── forecast/
│   │   ├── baseline.py         Point forecast (momentum + shrinkage)
│   │   └── interval.py         Interval forecast (realized vol, clamped)
│   ├── miner/
│   │   ├── adapter.py          Asset name ↔ Binance symbol + cm fallback
│   │   └── forward_custom.py   Precog forward function (deployed to precog/miners/)
│   ├── eval/
│   │   ├── recorder.py         JSONL logger + realized-outcome back-fill
│   │   └── metrics.py          APE + interval score (mirrors Precog reward.py)
│   └── utils/
│       ├── logging_utils.py    CLI logging setup
│       └── time_utils.py       UTC helpers
└── tests/
    ├── test_forecast_shapes.py
    ├── test_interval_validity.py
    └── test_fallbacks.py
```

---

## Quick start

### 1. Install our package

```bash
git clone <this-repo> ~/precog-baseline-miner
cd ~/precog-baseline-miner
pip install -e .
pip install -e ".[dev]"   # also installs pytest
```

### 2. Local smoke test (no Bittensor needed)

```bash
python -m precog_baseline_miner.main
```

Expected output:
```
btc                   spot=$ 65,432.10  point=$ 65,435.20  interval=[$ 64,800.00, $ 66,070.00]  width=1.95%
eth                   spot=$  3,210.50  point=$  3,210.90  interval=[$ 3,177.00, $  3,244.00]   width=2.10%
tao_bittensor         spot=$    120.10  point=$    120.05  interval=[$ 118.20,  $   121.80]    width=2.99%

Forecast log: /home/youruser/.precog_baseline/forecasts.jsonl
```

### 3. Run unit tests

```bash
pytest tests/ -v
```

All 3 test files should pass without network access (tests use synthetic data).

---

## Deploying to the Precog subnet

### Step 1 — Deploy

```bash
./deploy.sh
# This will:
#   1. Clone https://github.com/coinmetrics/precog to ~/precog
#   2. pip install the Precog package
#   3. pip install our package
#   4. Copy src/miner/forward_custom.py → ~/precog/precog/miners/baseline_miner.py
#   5. Create ~/precog/.env.miner from .env.example
```

### Step 2 — Configure wallet

Edit `~/precog/.env.miner`:

```dotenv
NETWORK=testnet          # or finney for mainnet
COLDKEY=miner            # your btcli coldkey name
MINER_HOTKEY=default     # your btcli hotkey name
FORWARD_FUNCTION=baseline_miner
```

Create wallet keys if you haven't yet:
```bash
btcli wallet new_coldkey --wallet.name miner
btcli wallet new_hotkey  --wallet.name miner --wallet.hotkey default
```

### Step 3 — Register on the subnet

```bash
# Find the Precog netuid (check https://github.com/coinmetrics/precog for current value)
PRECOG_NETUID=<netuid>
btcli s register --netuid $PRECOG_NETUID --wallet.name miner --wallet.hotkey default
```

### Step 4 — Open miner port

```bash
sudo ufw allow 8092/tcp
```

### Step 5 — Start the miner

```bash
cd ~/precog
make miner ENV_FILE=.env.miner
```

### Step 6 — Monitor

```bash
# Watch forecasts in real time
tail -f ~/.precog_baseline/forecasts.jsonl | python -m json.tool

# Check pm2 logs
pm2 logs baseline-miner
```

---

## Forecast logic

### Point forecast (`src/forecast/baseline.py`)

```
drift  = 0.7 × ret_5m + 0.3 × ret_15m
point  = spot × (1 + k × drift)       k = POINT_SHRINKAGE (default 0.10)
```

- Blends 5-minute and 15-minute momentum
- Heavily shrinks toward current spot (k=0.10 means 10% of raw signal)
- Falls back to spot (persistence) if fewer than 16 candles

### Interval forecast (`src/forecast/interval.py`)

```
hourly_vol  = std(1-min returns) × √60
half_width  = clamp(M × hourly_vol × point, min=0.1%, max=7.5%)
[low, high] = [point − half, point + half]   M = INTERVAL_MULTIPLIER (default 1.0)
```

- Symmetric around the point forecast
- Width automatically tracks realized volatility
- Clamped to prevent degenerate (zero-width) or absurdly wide intervals

### Reward optimisation (future work)

Precog scores intervals as `inclusion_factor × width_factor`:
- **inclusion_factor** = fraction of actual 1s prices inside `[low, high]`
- **width_factor** = overlap with observed price range / predicted width

The current baseline targets a modest width (~1–4% total), which should
earn reasonable scores without being too sloppy. Tune `INTERVAL_MULTIPLIER`
(wider → better inclusion, worse width) or swap in a better volatility model.

---

## Tuning via environment variables

| Variable | Default | Effect |
|---|---|---|
| `POINT_SHRINKAGE` | `0.10` | Lower → closer to persistence. Raise cautiously. |
| `INTERVAL_MULTIPLIER` | `1.0` | Raise → wider interval (better inclusion, lower width factor) |
| `PRECOG_BASELINE_LOG_DIR` | `~/.precog_baseline` | Where to write `forecasts.jsonl` |
| `BINANCE_TIMEOUT` | `10` | Seconds to wait for Binance API response |

---

## Offline evaluation

After an hour has passed, run:

```bash
python -c "
from precog_baseline_miner.eval.recorder import fill_realized
n = fill_realized()
print(f'Updated {n} records')
"
```

Then inspect `~/.precog_baseline/forecasts.jsonl` — each record will have:
- `ape` — absolute percentage error (lower is better)
- `interval_score` — approximate inclusion × width score (higher is better)

---

## Going further (Phase E)

Once the baseline is live and logging, you can improve it by:

1. **Better point forecast** — add realized vol as a feature, use a
   gradient-boosted regressor trained on your logged data.
2. **Better interval** — use a quantile regression or GARCH model.
3. **More data** — add 5-min candles, funding rates, open interest.
4. **Calibration** — track your APE and interval score in `forecasts.jsonl`
   and tune `POINT_SHRINKAGE` / `INTERVAL_MULTIPLIER` empirically.

See `INTERFACE_NOTES.md` for the exact Precog scoring formulas.
