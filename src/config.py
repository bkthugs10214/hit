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

# ── Candle exchanges ─────────────────────────────────────────────────────────
# Primary exchange. US users: set to https://api.binance.us (TAO not listed there).
# Leave blank for global api.binance.com.
BINANCE_BASE_URL = os.environ.get("BINANCE_BASE_URL", "https://api.binance.com")
# Secondary exchange: MEXC uses the identical Binance klines API format.
# Used automatically when the primary exchange returns "Invalid symbol" for an asset.
# TAO is available on MEXC even when using Binance.US as primary.
MEXC_BASE_URL = os.environ.get("MEXC_BASE_URL", "https://api.mexc.com")
# Seconds before giving up on a candle request (applies to both exchanges).
BINANCE_REQUEST_TIMEOUT = int(os.environ.get("BINANCE_TIMEOUT", "10"))

# ── Futures data (MEXC perpetual contracts) ───────────────────────────────────
# MEXC futures are accessible from the US where Binance/Bybit futures are blocked.
MEXC_FUTURES_BASE_URL = os.environ.get("MEXC_FUTURES_BASE_URL", "https://contract.mexc.com")
# Seconds to cache futures ticker per asset before re-fetching.
FUTURES_CACHE_TTL = int(os.environ.get("FUTURES_CACHE_TTL", "60"))
# Weight of futures signal in point forecast drift blend [0, 1].
FUTURES_WEIGHT = float(os.environ.get("FUTURES_WEIGHT", "0.10"))
FUTURES_LOG_FILE = LOG_DIR / "futures.jsonl"

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

# ── Sentiment data sources ────────────────────────────────────────────────────
# Free API key from cryptopanic.com — leave empty to disable CryptoPanic.
CRYPTOPANIC_API_KEY = os.environ.get("CRYPTOPANIC_API_KEY", "")
# Seconds to cache Fear & Greed result (updates daily; 300s is safe default).
SENTIMENT_CACHE_TTL = int(os.environ.get("SENTIMENT_CACHE_TTL", "300"))
# Weight of the sentiment signal in the point forecast drift blend [0, 1].
SENTIMENT_WEIGHT = float(os.environ.get("SENTIMENT_WEIGHT", "0.15"))
# Seconds before giving up on a sentiment API request.
SENTIMENT_REQUEST_TIMEOUT = int(os.environ.get("SENTIMENT_TIMEOUT", "5"))
SENTIMENT_LOG_FILE = LOG_DIR / "sentiment.jsonl"

# ── Verbose logging ───────────────────────────────────────────────────────────
# Set PRECOG_VERBOSE=1 to enable raw API payload logging in sentiment modules.
VERBOSE = os.environ.get("PRECOG_VERBOSE", "0") == "1"

# ── Network & deployment target ───────────────────────────────────────────────
# testnet = free test TAO, safe to experiment.
# finney  = Bittensor mainnet, real TAO.
NETWORK = os.environ.get("NETWORK", "testnet")
IS_MAINNET = NETWORK == "finney"

# ── Risk limits ───────────────────────────────────────────────────────────────
# Set RISK_LIMITS_ENABLED=0 to disable all pre-flight guards (not recommended on mainnet).
RISK_LIMITS_ENABLED = os.environ.get("RISK_LIMITS_ENABLED", "1") == "1"
# Miner refuses to start if coldkey balance is below this threshold.
MIN_BALANCE_TAO = float(os.environ.get("MIN_BALANCE_TAO", "1.0"))
# Wallet identifiers — used by run_miner.sh for balance checks.
COLDKEY = os.environ.get("COLDKEY", "miner")
MINER_HOTKEY = os.environ.get("MINER_HOTKEY", "default")
