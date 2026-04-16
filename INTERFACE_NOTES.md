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

Set `FORWARD_FUNCTION=baseline_miner` in your `.env.miner` to load our custom module.

---

## 3. CMData API (available as `cm` in forward function)

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

## 4. Reward Functions

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

## 5. Key Constants

| Constant | Value |
|---|---|
| Supported assets | `["tao_bittensor", "btc", "eth"]` |
| Prediction cadence | every 5 minutes |
| Prediction horizon | 1 hour |
| Validator timeout | ~20 s (env default 16 s) |
| Bittensor version | `^9.9.0` |
| Python | `>=3.9, <3.12` |

---

## 6. Timestamp Format

All timestamps use ISO 8601 with microseconds and Z suffix:
```
"2024-11-14T18:15:00.000000Z"
```
Timezone is always UTC. Use `precog.utils.timestamp` helpers:
```python
from precog.utils.timestamp import to_datetime, to_str, get_now, get_before, round_to_interval
```

---

## 7. How to Run the Miner

```bash
# Default (base_miner)
make miner ENV_FILE=.env.miner

# Custom forward function
# 1. Place your module at precog/miners/my_module.py
# 2. Set FORWARD_FUNCTION=my_module in .env.miner
# 3. make miner ENV_FILE=.env.miner
```

---

## 8. Minimum Viable Response

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
