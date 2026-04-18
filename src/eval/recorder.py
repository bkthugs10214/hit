"""
Forecast logger and offline evaluator — raw archive backend.

log_forecast()  writes an immutable event to the raw archive (Layer 2).
fill_realized() finds unfilled forecasts, fetches realized prices from
                Binance, and appends realization events to the archive.

After recording, call storage.serve.run_pipeline(DATA_DIR) to push data
through the normalization + serving layers.
"""
import logging
import time
from datetime import datetime, timedelta, timezone

from precog_baseline_miner.config import DATA_DIR
from precog_baseline_miner.eval.metrics import ape as compute_ape
from precog_baseline_miner.eval.metrics import interval_score as compute_interval_score
from precog_baseline_miner.storage import archive

logger = logging.getLogger(__name__)


def log_forecast(
    asset: str,
    timestamp: str,
    spot: float,
    point: float,
    low: float,
    high: float,
    binance_snap: dict | None = None,
    cm_snap: dict | None = None,
    *,
    latency_binance_ms: float | None = None,
    latency_cm_ms: float | None = None,
    latency_forward_ms: float | None = None,
) -> None:
    """
    Append one forecast event to the raw archive.

    Latency args (keyword-only):
        latency_binance_ms  — Binance klines round-trip time in ms
        latency_cm_ms       — CoinMetrics reference-rates round-trip time in ms
        latency_forward_ms  — total per-asset forward turnaround time in ms

    Silently swallows errors so a storage failure never crashes the forward
    function.
    """
    b = binance_snap or {}
    c = cm_snap or {}

    payload = {
        "prediction_ts": timestamp,
        "asset":         asset,
        "spot":          spot,
        "point":         point,
        "low":           low,
        "high":          high,
        # Binance snapshot (b_* prefix matches normalized schema)
        "b_ret_5m":      b.get("ret_5m"),
        "b_ret_15m":     b.get("ret_15m"),
        "b_ret_60m":     b.get("ret_60m"),
        "b_rvol_1m":     b.get("rvol_1m"),
        "b_volume_60m":  b.get("volume_60m"),
        "b_vwap_60m":    b.get("vwap_60m"),
        "b_n_candles":   b.get("n_candles"),
        # CoinMetrics snapshot
        "cm_available":  1 if c.get("available") else 0,
        "cm_spot":       c.get("cm_spot"),
        "cm_ret_1h":     c.get("cm_ret_1h"),
        "cm_rvol_1m":    c.get("cm_rvol_1m"),
        "cm_n_obs":      c.get("n_observations"),
        "cm_frequency":  c.get("frequency"),
        "cm_source":     c.get("source"),
        # Latency telemetry
        "latency_binance_ms":  latency_binance_ms,
        "latency_cm_ms":       latency_cm_ms,
        "latency_forward_ms":  latency_forward_ms,
    }

    try:
        archive.write_event(DATA_DIR, "precog", "forecasts", asset, payload)
    except Exception as exc:
        logger.error("Failed to archive forecast: %s", exc)


def fill_realized() -> int:
    """
    Find forecasts whose 1-hour horizon has elapsed but have no realization
    event yet, fetch realized prices from Binance, and write realization
    events to the raw archive.

    Returns the count of new realization events written.
    """
    # Import here to avoid circular import (binance_client → config, not eval)
    from precog_baseline_miner.data.binance_client import fetch_candles

    # Build map of all known forecasts: (asset, prediction_ts) → payload
    forecast_map: dict[tuple[str, str], dict] = {}
    for event in archive.iter_events(DATA_DIR, "precog", "forecasts"):
        p = event["payload"]
        key = (p.get("asset", ""), p.get("prediction_ts", ""))
        forecast_map[key] = p

    # Collect already-realized (asset, prediction_ts) pairs
    realized_keys: set[tuple[str, str]] = set()
    for event in archive.iter_events(DATA_DIR, "precog", "realizations"):
        p = event["payload"]
        realized_keys.add((p.get("asset", ""), p.get("prediction_ts", "")))

    now = datetime.now(timezone.utc)
    updated = 0

    for (asset, pred_ts_str), forecast in forecast_map.items():
        if (asset, pred_ts_str) in realized_keys:
            continue

        try:
            pred_ts = datetime.fromisoformat(pred_ts_str.replace("Z", "+00:00"))
        except ValueError:
            continue

        eval_ts = pred_ts + timedelta(hours=1)
        if eval_ts > now:
            continue

        try:
            start_ms = int(pred_ts.timestamp() * 1000)
            end_ms   = int(eval_ts.timestamp() * 1000)

            candles, b_latency_ms = fetch_candles(
                asset,
                interval="1m",
                limit=65,
                start_ms=start_ms,
                end_ms=end_ms,
            )

            if candles.empty:
                logger.warning("No candles returned for %s fill_realized", asset)
                continue

            realized_price = float(candles["close"].iloc[-1])
            realized_min   = float(candles["low"].min())
            realized_max   = float(candles["high"].max())

            realization = {
                "prediction_ts":     pred_ts_str,
                "asset":             asset,
                "realized_price_1h": realized_price,
                "realized_min_1h":   realized_min,
                "realized_max_1h":   realized_max,
                "ape":               compute_ape(forecast["point"], realized_price),
                "interval_score":    compute_interval_score(
                    forecast["low"], forecast["high"],
                    realized_min, realized_max,
                ),
                "latency_binance_ms": b_latency_ms,
            }
            archive.write_event(DATA_DIR, "precog", "realizations", asset, realization)
            updated += 1

        except Exception as exc:
            logger.warning(
                "Could not fill realized for asset=%s ts=%s: %s",
                asset, pred_ts_str, exc,
            )

    if updated:
        logger.info("fill_realized: archived %d new realization(s)", updated)

    return updated
