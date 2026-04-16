"""
Configuration for precog-baseline-miner.

All values read from environment variables so they can be set in .env.miner
or overridden on the command line before running the miner.
"""
import os
from pathlib import Path

# ── Forecast log directory ────────────────────────────────────────────────────
# Forecasts are appended to FORECAST_LOG_FILE as newline-delimited JSON.
LOG_DIR = Path(
    os.environ.get("PRECOG_BASELINE_LOG_DIR", "")
    or Path.home() / ".precog_baseline"
)
LOG_DIR.mkdir(parents=True, exist_ok=True)
FORECAST_LOG_FILE = LOG_DIR / "forecasts.jsonl"

# ── Binance REST API ──────────────────────────────────────────────────────────
BINANCE_BASE_URL = "https://api.binance.com"
# Seconds before giving up on a Binance request
BINANCE_REQUEST_TIMEOUT = int(os.environ.get("BINANCE_TIMEOUT", "10"))

# ── Candle defaults ───────────────────────────────────────────────────────────
DEFAULT_CANDLE_INTERVAL = "1m"
# 100 x 1-min candles = ~100 minutes of history (enough for 5m + 15m returns
# and 60-minute realized volatility)
DEFAULT_CANDLE_LIMIT = 100

# ── Forecast hyper-parameters (tunable via env) ───────────────────────────────
# Shrinkage applied to raw momentum drift.
# 0.0 = pure persistence (always predict current spot)
# 1.0 = full momentum projection
# Default 0.10 is conservative and stable.
POINT_SHRINKAGE = float(os.environ.get("POINT_SHRINKAGE", "0.10"))

# Multiplier on the realized-vol half-width.
# 1.0 targets ≈1 hourly-std wide on each side.
# Increase to widen intervals (better inclusion, lower width_factor).
INTERVAL_MULTIPLIER = float(os.environ.get("INTERVAL_MULTIPLIER", "1.0"))
