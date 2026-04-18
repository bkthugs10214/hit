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
import time

# ── Allow running as `python src/main.py` (before pip install) ───────────────
# When installed via `pip install -e .`, the imports below work automatically.
# When run directly, we add the project root to sys.path so that setup.py's
# package_dir mapping is replicated at runtime.
import os as _os
_here = _os.path.dirname(_os.path.abspath(__file__))
_root = _os.path.dirname(_here)
if _root not in sys.path:
    sys.path.insert(0, _root)

from precog_baseline_miner.config import DATA_DIR
from precog_baseline_miner.data.binance_client import fetch_candles
from precog_baseline_miner.data.candles import binance_snapshot
from precog_baseline_miner.data.cm_client import cm_snapshot, fetch_reference_rates
from precog_baseline_miner.eval.recorder import fill_realized, log_forecast
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
            _t0 = time.perf_counter()

            candles, b_latency_ms = fetch_candles(asset, limit=100)
            spot  = float(candles["close"].iloc[-1])
            point = compute_point_forecast(candles)
            lo, hi = compute_interval(candles, point)
            b_snap = binance_snapshot(candles)

            # CoinMetrics — best-effort, never blocks the forecast
            cm_latency_ms: float | None = None
            try:
                cm_df, cm_latency_ms = fetch_reference_rates(asset, frequency="1m", lookback_hours=1)
                c_snap = cm_snapshot(cm_df)
                cm_spot_str = f"  cm_spot=${c_snap['cm_spot']:>12,.2f}" if c_snap.get("cm_spot") else "  cm_spot=unavailable"
            except Exception as cm_exc:
                c_snap = {"available": False}
                cm_spot_str = f"  cm_spot=error({cm_exc.__class__.__name__})"

            forward_ms = round((time.perf_counter() - _t0) * 1000, 1)
            latency_str = (
                f"  binance:{b_latency_ms:.0f}ms"
                + (f"  cm:{cm_latency_ms:.0f}ms" if cm_latency_ms is not None else "")
                + f"  total:{forward_ms:.0f}ms"
            )

            print(
                f"  {asset:<20}  "
                f"spot=${spot:>12,.2f}{cm_spot_str}  "
                f"point=${point:>12,.2f}  "
                f"interval=[${lo:>12,.2f}, ${hi:>12,.2f}]  "
                f"width={100*(hi-lo)/point:.2f}%{latency_str}"
            )

            log_forecast(
                asset=asset,
                timestamp=timestamp,
                spot=spot,
                point=point,
                low=lo,
                high=hi,
                binance_snap=b_snap,
                cm_snap=c_snap,
                latency_binance_ms=b_latency_ms,
                latency_cm_ms=cm_latency_ms,
                latency_forward_ms=forward_ms,
            )
            any_success = True

        except Exception as exc:
            logger.error("  %-20s  FAILED: %s", asset, exc)

    print()
    print(f"Data dir:  {DATA_DIR}")

    # Back-fill realized outcomes for past forecasts, then run storage pipeline
    filled = fill_realized()
    if filled:
        print(f"Back-filled realized outcomes for {filled} past forecast(s).")

    from precog_baseline_miner.storage.serve import run_pipeline
    pipeline = run_pipeline(DATA_DIR)
    if any(pipeline.values()):
        written = ", ".join(f"{k}={v}" for k, v in pipeline.items() if v)
        print(f"Pipeline: {written}")

    return any_success


if __name__ == "__main__":
    ok = run_once()
    sys.exit(0 if ok else 1)
