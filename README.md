# precog-baseline-miner

A simple, valid, improvable baseline miner for the
[Coin Metrics Precog subnet](https://github.com/coinmetrics/precog) on Bittensor.

The miner:
- Fetches 1-minute OHLCV candles from Binance (public API, no key required)
- Produces a **point forecast** blending momentum + sentiment + futures signals
- Produces an **interval forecast** using realized volatility
- Handles all three Precog assets: BTC, ETH, TAO
- Logs every forecast to `~/.precog_baseline/forecasts.jsonl`
- Logs sentiment signals to `~/.precog_baseline/sentiment.jsonl`
- Logs futures signals to `~/.precog_baseline/futures.jsonl`
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
├── run_miner.sh           Pre-flight checks then starts the miner
├── src/
│   ├── config.py          Reads env vars (shrinkage, log dir, weights, …)
│   ├── main.py            Standalone smoke test (no Bittensor required)
│   ├── data/
│   │   ├── binance_client.py        Binance REST API: fetch 1-min candles
│   │   ├── candles.py               DataFrame helpers
│   │   ├── sentiment/
│   │   │   ├── __init__.py          Aggregator: fetch_all_sentiment(asset) → SentimentBundle
│   │   │   ├── fear_greed.py        alternative.me Fear & Greed Index (TTL-cached)
│   │   │   ├── cryptopanic.py       CryptoPanic news sentiment (requires free API key)
│   │   │   └── reddit.py            Reddit hot-post upvote-ratio sentiment (no key)
│   │   └── futures/
│   │       ├── __init__.py          Aggregator: fetch_all_futures(asset) → FuturesBundle
│   │       └── mexc_futures.py      MEXC funding rate + open interest
│   ├── features/
│   │   ├── returns.py               5-min / 15-min momentum returns
│   │   ├── volatility.py            Realized vol → hourly vol estimate
│   │   ├── sentiment.py             Normalize SentimentBundle → float signal [-1, 1]
│   │   └── futures.py               Normalize FuturesBundle → float signal [-1, 1]
│   ├── forecast/
│   │   ├── baseline.py              Point forecast (momentum + sentiment + futures blend)
│   │   └── interval.py              Interval forecast (realized vol, clamped)
│   ├── miner/
│   │   ├── adapter.py               Asset name ↔ Binance symbol + cm fallback
│   │   └── forward_custom.py        Precog forward function (deployed to precog/miners/)
│   ├── eval/
│   │   ├── recorder.py              JSONL logger + realized-outcome back-fill
│   │   ├── sentiment_recorder.py    Appends to sentiment.jsonl
│   │   ├── futures_recorder.py      Appends to futures.jsonl
│   │   └── metrics.py               APE + interval score (mirrors Precog reward.py)
│   ├── risk/
│   │   └── guards.py                Pre-flight safety checks (balance, registration)
│   └── utils/
│       ├── logging_utils.py         CLI logging setup
│       └── time_utils.py            UTC helpers
└── tests/
    ├── test_forecast_shapes.py
    ├── test_interval_validity.py
    └── test_fallbacks.py
```

---

## Quick start

### 1. Install

```bash
cd ~/precog/hit
source .venv/bin/activate   # use the project venv (required — system pip is PEP 668 blocked)
pip install -e .
pip install -e ".[dev]"     # also installs pytest
```

### 2. Local smoke test (no Bittensor needed)

```bash
BINANCE_BASE_URL=https://api.binance.us python src/main.py
```

Expected output (values will differ):
```
btc                   spot=$  94,328.00  point=$  94,330.00  interval=[$93,500.00, $95,160.00]  width=1.76%  F&G=33(Fear)  Reddit=+0.748(25p)  funding=-0.000012  sent=-0.029  fut=+0.013
eth                   spot=$   1,783.00  ...
tao_bittensor         spot=$     389.00  ...

Forecast log:  ~/.precog_baseline/forecasts.jsonl
Sentiment log: ~/.precog_baseline/sentiment.jsonl
Futures log:   ~/.precog_baseline/futures.jsonl
```

### 3. Run unit tests

```bash
pytest tests/ -v
```

All test files should pass without network access (tests use synthetic data).

---

## Sentiment signals

Three sources are blended into a single `[-1, 1]` signal. Each source is optional —
if unavailable, its weight is redistributed proportionally to remaining sources.

| Source | Weight | Notes |
|--------|--------|-------|
| Fear & Greed Index | 50% | alternative.me; asset-agnostic macro mood; TTL-cached |
| CryptoPanic news | 30% | Requires free API key (`CRYPTOPANIC_API_KEY`); disabled if blank |
| Reddit hot posts | 20% | Public JSON API; per-asset subreddit; no key required |

**Scoring:**
- Fear & Greed: `(value - 50) / 50` → maps 0=extreme fear→-1, 100=extreme greed→+1
- Reddit: `Σ(log1p(karma) × (upvote_ratio - 0.5) × 2) / Σ(log1p(karma))` → [-1, 1]
- CryptoPanic: vote-weighted news score already in [-1, 1]

---

## Futures signals

MEXC perpetual futures data provides a market-structure signal:

| Field | Signal direction |
|-------|-----------------|
| Funding rate | Positive rate → longs pay shorts → bearish lean |
| Open interest change | Rising OI with rising price → bullish confirmation |

Combined into a single `[-1, 1]` futures signal blended into the point forecast.

---

## Forecast logic

### Point forecast (`src/forecast/baseline.py`)

```
momentum = 0.7 × ret_5m + 0.3 × ret_15m
drift    = (1 - sentiment_weight - futures_weight) × momentum
         + sentiment_weight × sentiment_signal
         + futures_weight   × futures_signal
point    = spot × (1 + k × drift)       k = POINT_SHRINKAGE (default 0.10)
```

- Falls back to momentum-only if sentiment/futures signals are None
- Falls back to spot (persistence) if fewer than 16 candles

### Interval forecast (`src/forecast/interval.py`)

```
hourly_vol  = std(1-min returns) × √60
half_width  = clamp(M × hourly_vol × point, min=0.1%, max=7.5%)
[low, high] = [point − half, point + half]   M = INTERVAL_MULTIPLIER (default 1.0)
```

- Symmetric around the point forecast
- Width automatically tracks realized volatility
- Clamped to prevent degenerate or absurdly wide intervals

### Reward optimisation

Precog scores intervals as `inclusion_factor × width_factor`:
- **inclusion_factor** = fraction of actual 1s prices inside `[low, high]`
- **width_factor** = overlap with observed price range / predicted width

Current baseline targets ~1–4% total width. Tune `INTERVAL_MULTIPLIER` to trade
off inclusion vs. width.

---

## Deploying to the Precog subnet

### Step 1 — Deploy

```bash
cd ~/precog/hit
bash deploy.sh
# Clones https://github.com/coinmetrics/precog to ~/precog-node
# Creates ~/precog-node/.venv with Python 3.11
# Installs Precog + our package into the same venv
# Copies src/miner/forward_custom.py → ~/precog-node/precog/miners/baseline_miner.py
# Creates ~/precog-node/.env.miner from .env.example
```

### Step 2 — Configure wallet

Edit `~/precog-node/.env.miner`:

```dotenv
NETWORK=testnet              # or finney for mainnet
COLDKEY=miner                # your btcli coldkey name
MINER_HOTKEY=default         # your btcli hotkey name
FORWARD_FUNCTION=baseline_miner
BINANCE_BASE_URL=https://api.binance.us   # required for US IPs
MIN_BALANCE_TAO=0.5          # lower threshold for testnet (testnet balance is ~1 TAO)
```

### Step 3 — Create wallet keys

```bash
btcli wallet new_coldkey --wallet.name miner
btcli wallet new_hotkey  --wallet.name miner --wallet.hotkey default
```

### Step 4 — Get testnet TAO and register

```bash
# 1. Get testnet TAO from the Bittensor Discord #faucet channel
#    Request: !request <your-coldkey-ss58-address>

# 2. Register on the Precog subnet
#    Testnet netuid = 256  (NOT 50 — the Precog Makefile hardcodes 256 for testnet)
btcli subnet register --netuid 256 --network test \
  --wallet.name miner --wallet.hotkey default
# Cost: ~0.0005 TAO
```

> **Note:** netuid 50 is a different subnet (audio). Precog testnet is 256. Mainnet is 55.

### Step 5 — Install pm2

The Precog Makefile uses pm2 to manage the miner process. Install it once:

```bash
npm install -g pm2
```

### Step 6 — Open miner port

**Linux (bare metal or VM):**
```bash
sudo ufw allow 8092/tcp
```

**WSL2 on Windows:** Port 8092 listens inside the WSL2 VM — you need two forwarding hops.

*Step 6a — Forward WSL2 → Windows host* (PowerShell as Administrator):
```powershell
# Replace 172.25.85.65 with your WSL2 IP (run `hostname -I` in WSL to find it)
netsh interface portproxy add v4tov4 listenport=8092 listenaddress=0.0.0.0 connectport=8092 connectaddress=172.25.85.65
netsh advfirewall firewall add rule name="Precog Miner 8092" dir=in action=allow protocol=TCP localport=8092
```

*Step 6b — Forward router → Windows host:*
Log into your router admin page and add a TCP port forward: external 8092 → your Windows LAN IP (find it with `ipconfig | findstr IPv4`).

**Double NAT (e.g. ISP modem + home router):** Add the port forward on both routers, chaining from the outer router to the inner router's WAN IP, then from the inner router to the Windows machine.

### Step 7 — Start the miner

```bash
PRECOG_DIR=~/precog-node ~/precog/hit/run_miner.sh
```

### Step 8 — Verify port is reachable externally

```bash
# From inside WSL — should return axon synapse info, not "Connection refused"
curl -s http://<your-public-ip>:8092
# Expected: {"message":"Synapse name '' not found. Available synapses ['Synapse', 'Challenge']"}
```

Find your public IP with `curl -s https://api.ipify.org`. You can also use [portchecker.co](https://portchecker.co) to probe from a third-party server.

### Step 9 — Monitor

Each `run_miner.sh` invocation creates a new timestamped log file in `~/precog/hit/logs/`:

```
logs/
  baseline-miner-2026-04-22T00-07-00Z-out.log   # bt.logging + forward function output
  baseline-miner-2026-04-22T00-07-00Z-err.log   # Python tracebacks
  baseline-miner-<timestamp>/                    # bt.logging file output (--logging.record)
```

```bash
# Watch the latest miner output log
tail -f ~/precog/hit/logs/baseline-miner-*-out.log | tail -f $(ls -t ~/precog/hit/logs/*-out.log | head -1)

# Simpler: check pm2 which log file is active
pm2 list

# Watch forecasts in real time
tail -f ~/.precog_baseline/forecasts.jsonl | python -m json.tool

# Watch sentiment signals
tail -f ~/.precog_baseline/sentiment.jsonl | python -m json.tool

# Watch futures signals
tail -f ~/.precog_baseline/futures.jsonl | python -m json.tool
```

A successful validator hit looks like:
```
2026-04-22T12:00:00.000 | SUCCESS | Predictions: {'btc': 94330.0, ...} | Intervals: {'btc': [93500.0, 95160.0], ...}
```

### Step 10 — Persist across reboots

```bash
pm2 startup   # prints a command — run it as instructed
pm2 save      # saves current process list
```

> **WSL2 note:** The WSL2 internal IP (`172.25.85.65`) can change on reboot. Re-run the `netsh interface portproxy` command after each reboot, or automate it with a Windows startup script.

---

## Tuning via environment variables

| Variable | Default | Effect |
|---|---|---|
| `POINT_SHRINKAGE` | `0.10` | Lower → closer to persistence. Raise cautiously. |
| `INTERVAL_MULTIPLIER` | `1.0` | Raise → wider interval (better inclusion, lower width factor) |
| `SENTIMENT_WEIGHT` | `0.15` | Fraction of forecast drift from sentiment signal |
| `FUTURES_WEIGHT` | `0.10` | Fraction of forecast drift from futures signal |
| `SENTIMENT_CACHE_TTL` | `300` | Seconds to cache Fear & Greed before re-fetching |
| `CRYPTOPANIC_API_KEY` | `""` | Free key from cryptopanic.com; leave blank to disable |
| `PRECOG_VERBOSE` | `0` | Set to `1` to log raw API payloads and per-source scores |
| `BINANCE_BASE_URL` | `""` | Set to `https://api.binance.us` for US IPs |
| `PRECOG_BASELINE_LOG_DIR` | `~/.precog_baseline` | Where to write JSONL log files |
| `MIN_BALANCE_TAO` | `1.0` | Miner refuses to start below this balance (use `0.5` on testnet) |

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

Each `forecasts.jsonl` record will then have:
- `ape` — absolute percentage error (lower is better)
- `interval_score` — approximate inclusion × width score (higher is better)

---

## Testnet status

| Field | Value |
|-------|-------|
| Network | testnet |
| Subnet (netuid) | 256 (Precog testnet) |
| Miner UID | 230 |
| Coldkey | `miner` |
| Hotkey | `default` |
| Balance after registration | ~0.9935 TAO |
| Axon port | 8092 (confirmed reachable externally) |
| Public IP | 108.30.180.159 |

---

## Roadmap (future improvements)

1. **Better point forecast** — gradient-boosted regressor trained on logged `forecasts.jsonl` data
2. **Better interval** — quantile regression or GARCH model
3. **More features** — 5-min candles, taker buy/sell ratio, OI change rate as interval-width feature
4. **Calibration** — track APE and interval score empirically; tune `POINT_SHRINKAGE` / `INTERVAL_MULTIPLIER`
5. **Mainnet migration** — once testnet performance is stable

See `INTERFACE_NOTES.md` for the exact Precog scoring formulas.
