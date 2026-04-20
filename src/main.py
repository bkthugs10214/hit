"""
Standalone smoke test for precog-baseline-miner.

Runs one complete forecast cycle without starting the Bittensor miner.
Use this to verify that:
  - the Binance API is reachable
  - candles are being parsed correctly
  - the point and interval forecasts are reasonable
  - the log file is being written

Usage (after pip install -e .):
    python -m precog_baseline_miner.main
    # or equivalently:
    cd /home/user/hit && python src/main.py
"""
import logging
import sys

# ── Allow running as `python src/main.py` (before pip install) ───────────────
# When installed via `pip install -e .`, the imports below work automatically.
# When run directly, we add the project root to sys.path so that setup.py's
# package_dir mapping is replicated at runtime.
import os as _os
_here = _os.path.dirname(_os.path.abspath(__file__))
_root = _os.path.dirname(_here)
if _root not in sys.path:
    sys.path.insert(0, _root)

from precog_baseline_miner.config import FORECAST_LOG_FILE, SENTIMENT_LOG_FILE, SENTIMENT_WEIGHT
from precog_baseline_miner.data.binance_client import fetch_candles
from precog_baseline_miner.data.sentiment import fetch_all_sentiment
from precog_baseline_miner.eval.recorder import fill_realized, log_forecast
from precog_baseline_miner.eval.sentiment_recorder import log_sentiment
from precog_baseline_miner.features.sentiment import sentiment_signal
from precog_baseline_miner.forecast.baseline import compute_point_forecast
from precog_baseline_miner.forecast.interval import compute_interval
from precog_baseline_miner.miner.adapter import ASSET_SYMBOL_MAP
from precog_baseline_miner.utils.logging_utils import setup_logging
from precog_baseline_miner.utils.time_utils import iso_now

setup_logging("INFO")
logger = logging.getLogger(__name__)


def run_once() -> bool:
    """
    Run one forecast cycle for all supported assets.

    Returns True if at least one asset succeeded.
    """
    timestamp = iso_now()
    assets = list(ASSET_SYMBOL_MAP.keys())

    logger.info("─" * 60)
    logger.info("Precog baseline forecast  ts=%s", timestamp)
    logger.info("─" * 60)

    any_success = False

    for asset in assets:
        try:
            candles = fetch_candles(asset, limit=100)
            spot = float(candles["close"].iloc[-1])

            bundle = fetch_all_sentiment(asset)
            signal = sentiment_signal(bundle)
            log_sentiment(asset, bundle, signal)

            point = compute_point_forecast(
                candles,
                sentiment=signal,
                sentiment_weight=SENTIMENT_WEIGHT,
            )
            lo, hi = compute_interval(candles, point)

            fg_str = (
                f"F&G={bundle.fear_greed.value}({bundle.fear_greed.classification})"
                if bundle.fear_greed else "F&G=N/A"
            )
            cp_str = (
                f"CP={bundle.cryptopanic.score:+.3f}"
                if bundle.cryptopanic else "CP=N/A"
            )
            sig_str = f"signal={signal:+.3f}" if signal is not None else "signal=N/A"

            print(
                f"  {asset:<20}  "
                f"spot=${spot:>12,.2f}  "
                f"point=${point:>12,.2f}  "
                f"interval=[${lo:>12,.2f}, ${hi:>12,.2f}]  "
                f"width={100*(hi-lo)/point:.2f}%  "
                f"{fg_str}  {cp_str}  {sig_str}"
            )

            log_forecast(
                asset=asset,
                timestamp=timestamp,
                spot=spot,
                point=point,
                low=lo,
                high=hi,
            )
            any_success = True

        except Exception as exc:
            logger.error("  %-20s  FAILED: %s", asset, exc)

    print()
    print(f"Forecast log:  {FORECAST_LOG_FILE}")
    print(f"Sentiment log: {SENTIMENT_LOG_FILE}")

    # Try to fill any past forecasts whose 1-hour horizon has passed
    filled = fill_realized()
    if filled:
        print(f"Back-filled realized outcomes for {filled} past forecast(s).")

    return any_success


if __name__ == "__main__":
    ok = run_once()
    sys.exit(0 if ok else 1)
