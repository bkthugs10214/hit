# Precog Subnet — Miner Interface Notes

Researched from `coinmetrics/precog` (master branch). Use this as the source of truth
when building or debugging the miner forward function.

---

## 1. Synapse Object: `Challenge`

**File:** `precog/protocol.py`

```python
class Challenge(bt.Synapse):
    # Sent BY the validator TO the miner
    timestamp: str            # ISO 8601 UTC, e.g. "2024-11-14T18:15:00.000000Z"
    assets: List[str]         # e.g. ["tao_bittensor", "btc", "eth"] (default ["btc"])

    # Set BY the miner, returned TO the validator
    predictions: Optional[Dict[str, float]]         # {"btc": 65432.50, ...}
    intervals:   Optional[Dict[str, List[float]]]   # {"btc": [64500.0, 66500.0], ...}
```

- `predictions` — one point estimate per asset (USD price, float)
- `intervals` — one `[min, max]` pair per asset; represents the expected price
  range over the NEXT HOUR based on 1-second frequency data
- `deserialize()` returns the `predictions` dict

---

## 2. Forward Function Contract

**Must live at:** `precog/miners/{FORWARD_FUNCTION}.py`

```python
async def forward(synapse: Challenge, cm: CMData) -> Challenge:
    """
    Args:
        synapse  – the Challenge request; read .timestamp and .assets
        cm       – CoinMetrics data client (CMData); use for price history if needed

    Returns:
        The same synapse object with .predictions and .intervals populated.
    """
    synapse.predictions = {"btc": 65000.0, "eth": 3200.0, "tao_bittensor": 120.0}
    synapse.intervals   = {"btc": [64000.0, 66000.0], ...}
    return synapse
```

**Loaded dynamically by** `precog/miners/miner.py`:
```python
self.forward_module = importlib.import_module(f"precog.miners.{config.forward_function}")
# Called as:
synapse = await self.forward_module.forward(synapse, self.cm)
```

Set `FORWARD_FUNCTION=baseline_miner` in `.env.miner` to load our custom module.
Our forward function lives at `src/miner/forward_custom.py` and is deployed to
`~/precog-node/precog/miners/baseline_miner.py` by `deploy.sh`.

---

## 3. Our Forward Function Pipeline (`src/miner/forward_custom.py`)

Each validator call triggers this sequence per asset:

```
1. fetch_candles(asset, limit=100)          ← Binance 1-min OHLCV
2. fetch_all_sentiment(asset)               ← Fear & Greed + CryptoPanic + Reddit
3. sentiment_signal(bundle)                 ← normalize to [-1, 1]
4. log_sentiment(asset, bundle, signal)     ← append to sentiment.jsonl
5. fetch_all_futures(asset)                 ← MEXC funding rate + OI
6. futures_signal(bundle)                   ← normalize to [-1, 1]
7. log_futures(asset, bundle, signal)       ← append to futures.jsonl
8. compute_point_forecast(candles, ...)     ← momentum + sentiment + futures blend
9. compute_interval(candles, point)         ← realized vol half-width
10. log_forecast(asset, ...)                ← append to forecasts.jsonl
```

If any upstream step fails, that signal is `None` and the forecast degrades
gracefully to whatever data is available (minimum: Binance candles only).

---

## 4. CMData API (available as `cm` in forward function)

**File:** `precog/utils/cm_data.py`

```python
df = cm.get_CM_ReferenceRate(
    assets=["btc"],
    start="2024-11-14T17:15:00.000000Z",   # 1 hour before prediction time
    end="2024-11-14T18:15:00.000000Z",
    frequency="1s",
)
# Returns DataFrame with columns: ['asset', 'time', 'ReferenceRateUSD']
```

Our baseline uses Binance candles instead, so `cm` is only used as a fallback.

---

## 5. Reward Functions

**File:** `precog/validators/reward.py`

### Point forecast — APE (lower is better)
```
score = |predicted - actual| / actual
```
- Miners are ranked; lower APE = higher rank = larger reward.
- Weighted by rank with exponential decay (decay=0.8).

### Interval forecast — inclusion × width (higher is better)
```
inclusion_factor = (# of actual 1s prices inside [low, high]) / (total prices)
width_factor     = overlap([low, high], [obs_min, obs_max]) / (high - low)
score            = inclusion_factor × width_factor
```
- High inclusion + tight width = high score.
- Very wide intervals dilute the width factor even if inclusion is 1.0.

### Task weights
```python
TASK_WEIGHTS = {
    "btc":           {"point": 0.166, "interval": 0.166},
    "eth":           {"point": 0.166, "interval": 0.166},
    "tao_bittensor": {"point": 0.166, "interval": 0.166},
}
# 6 equal tasks, each ~16.6% of total reward
```

---

## 6. Key Constants

| Constant | Value |
|---|---|
| Supported assets | `["tao_bittensor", "btc", "eth"]` |
| Prediction cadence | every 5 minutes |
| Prediction horizon | 1 hour |
| Validator timeout | ~20 s (env default 16 s) |
| Bittensor version | `^9.9.0` |
| Python | `>=3.9, <3.12` |
| Testnet netuid | 256 (NOT 50 — the Precog Makefile hardcodes 256 for testnet) |
| Mainnet netuid | 55 |

---

## 7. Timestamp Format

All timestamps use ISO 8601 with microseconds and Z suffix:
```
"2024-11-14T18:15:00.000000Z"
```
Timezone is always UTC. Use `precog.utils.timestamp` helpers:
```python
from precog.utils.timestamp import to_datetime, to_str, get_now, get_before, round_to_interval
```

---

## 8. How to Run the Miner

```bash
# Always use run_miner.sh — it runs pre-flight checks and manages logging
PRECOG_DIR=~/precog-node ~/precog/hit/run_miner.sh
```

Pre-flight checks:
- btcli version matches `.btcli-version` pin
- Coldkey balance >= `MIN_BALANCE_TAO`
- Venv activated before pm2 launch
- Deletes old pm2 process so each run gets fresh timestamped log files

Logs are written to `~/precog/hit/logs/`:
- `baseline-miner-<timestamp>-out.log` — bt.logging + forward function stdout
- `baseline-miner-<timestamp>-err.log` — Python tracebacks
- `baseline-miner-<timestamp>/` — bt.logging file output (`--logging.record`)

pm2 is started with `--no-autorestart` — crashes require a manual `run_miner.sh` invocation to ensure a new log file is created.

---

## 9. Minimum Viable Response

```python
# Absolute minimum to avoid being penalised as a non-responder:
synapse.predictions = {"btc": <float>}
synapse.intervals   = {"btc": [<float_low>, <float_high>]}
# Ideally cover all 3 assets to earn rewards on all 6 tasks
```

Constraints:
- Both fields must be set (not None) for a valid response
- `intervals[asset][0] < intervals[asset][1]` (low < high)
- All values must be finite positive floats
- Response must arrive within the validator timeout (~16–20 s)

---

## 10. Deployment Paths

| Item | Path |
|------|------|
| This repo | `~/precog/hit` |
| Precog upstream | `~/precog-node` |
| Deployed forward function | `~/precog-node/precog/miners/baseline_miner.py` |
| Miner env config | `~/precog-node/.env.miner` |
| Forecast log | `~/.precog_baseline/forecasts.jsonl` |
| Sentiment log | `~/.precog_baseline/sentiment.jsonl` |
| Futures log | `~/.precog_baseline/futures.jsonl` |
| Wallets | `~/.bittensor/wallets/miner/` |
