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

from precog_baseline_miner.config import (
    FORECAST_LOG_FILE,
    FUTURES_LOG_FILE,
    FUTURES_WEIGHT,
    SENTIMENT_LOG_FILE,
    SENTIMENT_WEIGHT,
)
from precog_baseline_miner.data.binance_client import fetch_candles
from precog_baseline_miner.data.futures import fetch_all_futures
from precog_baseline_miner.data.sentiment import fetch_all_sentiment
from precog_baseline_miner.eval.futures_recorder import log_futures
from precog_baseline_miner.eval.recorder import fill_realized, log_forecast
from precog_baseline_miner.eval.sentiment_recorder import log_sentiment
from precog_baseline_miner.features.futures import futures_signal
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

            sent_bundle = fetch_all_sentiment(asset)
            sent_sig = sentiment_signal(sent_bundle)
            log_sentiment(asset, sent_bundle, sent_sig)

            fut_bundle = fetch_all_futures(asset)
            fut_sig = futures_signal(fut_bundle)
            log_futures(asset, fut_bundle, fut_sig)

            fcst = compute_point_forecast(
                candles,
                sentiment=sent_sig,
                sentiment_weight=SENTIMENT_WEIGHT,
                futures=fut_sig,
                futures_weight=FUTURES_WEIGHT,
            )
            itvl = compute_interval(candles, fcst.point)
            point, lo, hi = fcst.point, itvl.low, itvl.high

            fg_str = (
                f"F&G={sent_bundle.fear_greed.value}({sent_bundle.fear_greed.classification})"
                if sent_bundle.fear_greed else "F&G=N/A"
            )
            rd_str = (
                f"Reddit={sent_bundle.reddit.score:+.3f}({sent_bundle.reddit.post_count}p)"
                if sent_bundle.reddit else "Reddit=N/A"
            )
            fund_str = (
                f"funding={fut_bundle.mexc.funding_rate:+.6f}"
                if fut_bundle.mexc else "funding=N/A"
            )
            fut_sig_str = f"fut={fut_sig:+.3f}" if fut_sig is not None else "fut=N/A"
            sent_sig_str = f"sent={sent_sig:+.3f}" if sent_sig is not None else "sent=N/A"

            print(
                f"  {asset:<20}  "
                f"spot=${spot:>12,.2f}  "
                f"point=${point:>12,.2f}  "
                f"interval=[${lo:>12,.2f}, ${hi:>12,.2f}]  "
                f"width={100*(hi-lo)/point:.2f}%  "
                f"{fg_str}  {rd_str}  {fund_str}  {sent_sig_str}  {fut_sig_str}"
            )

            log_forecast(
                asset=asset,
                timestamp=timestamp,
                spot=spot,
                point=point,
                low=lo,
                high=hi,
                features={**fcst.features, **itvl.features},
            )
            any_success = True

        except Exception as exc:
            logger.error("  %-20s  FAILED: %s", asset, exc)

    print()
    print(f"Forecast log:  {FORECAST_LOG_FILE}")
    print(f"Sentiment log: {SENTIMENT_LOG_FILE}")
    print(f"Futures log:   {FUTURES_LOG_FILE}")

    # Try to fill any past forecasts whose 1-hour horizon has passed
    filled = fill_realized()
    if filled:
        print(f"Back-filled realized outcomes for {filled} past forecast(s).")

    return any_success


if __name__ == "__main__":
    ok = run_once()
    sys.exit(0 if ok else 1)
