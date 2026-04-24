"""
Forecast logger and offline evaluator.

Each forecast is appended to FORECAST_LOG_FILE (newline-delimited JSON).
One hour later, fill_realized() fetches the realized prices from Binance
and back-fills the `realized_*`, `ape`, and `interval_score` fields.

Log file location: ~/.precog_baseline/forecasts.jsonl  (configurable via env)

Record schema (v2)
------------------
{
  "logged_at":          "2026-04-24T18:15:01.123456Z",   # wall-clock time
  "prediction_ts":      "2026-04-24T18:15:00.000000Z",   # from synapse.timestamp
  "schema_version":     "v2",
  "asset":              "btc",
  "spot":               65000.0,    # price at prediction time
  "point":              65020.0,    # our point forecast
  "low":                63800.0,    # our interval lower bound
  "high":               66200.0,    # our interval upper bound
  "features": {                     # nested; only present when supplied
     "ret_5m":              0.00032,
     "ret_15m":            -0.00014,
     "point_shrinkage":     0.10,
     "sentiment_sig":      -0.42,   # absent if sentiment was None
     "sentiment_weight":    0.15,   # absent if sentiment was None
     "futures_sig":         0.038,  # absent if futures was None
     "futures_weight":      0.10,   # absent if futures was None
     "hourly_vol":          0.015,
     "interval_multiplier": 1.0
     # fallback rows use "point_fallback" / "interval_fallback" markers instead
  },
  "realized_price_1h":  null,       # filled 1h later
  "realized_min_1h":    null,       # filled 1h later (candle lows)
  "realized_max_1h":    null,       # filled 1h later (candle highs)
  "ape":                null,       # filled 1h later
  "interval_score":     null        # filled 1h later (approximate)
}

v1 rows (pre-Phase-1) lack `schema_version` and `features`. fill_realized()
tolerates both shapes — the on-disk row is rewritten in place, preserving
whichever schema it started with.
"""
import json
import logging
import threading
from datetime import datetime, timedelta, timezone

from precog_baseline_miner.config import FORECAST_LOG_FILE
from precog_baseline_miner.eval.metrics import ape as compute_ape
from precog_baseline_miner.eval.metrics import interval_score as compute_interval_score

logger = logging.getLogger(__name__)

# Thread-safe write lock — the miner may call log_forecast concurrently
# for multiple assets in the same request.
_write_lock = threading.Lock()


def log_forecast(
    asset: str,
    timestamp: str,
    spot: float,
    point: float,
    low: float,
    high: float,
    features: dict | None = None,
) -> None:
    """
    Append one forecast record to the JSONL log.

    Args:
        features: Optional nested dict of inputs that materially affected
                  point/low/high. When None, the `features` key is omitted
                  from the row entirely (so readers can distinguish "no
                  features captured" from "features captured as empty").

    Silently swallows I/O errors so that a logging failure never crashes
    the miner's forward function.
    """
    record = {
        "logged_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z",
        "prediction_ts": timestamp,
        "schema_version": "v2",
        "asset": asset,
        "spot": spot,
        "point": point,
        "low": low,
        "high": high,
        "realized_price_1h": None,
        "realized_min_1h": None,
        "realized_max_1h": None,
        "ape": None,
        "interval_score": None,
    }
    if features is not None:
        record["features"] = features

    with _write_lock:
        try:
            with open(FORECAST_LOG_FILE, "a") as fh:
                fh.write(json.dumps(record) + "\n")
        except Exception as exc:
            logger.error("Failed to write forecast log: %s", exc)


def fill_realized() -> int:
    """
    Back-fill realized prices for any forecasts whose 1-hour horizon has passed.

    Reads FORECAST_LOG_FILE, finds records where `realized_price_1h` is None
    and the horizon has elapsed, fetches the corresponding Binance candles,
    and rewrites the file with the filled-in values.

    Tolerates both v1 (no schema_version, no features) and v2 rows — each is
    rewritten preserving its original schema. No schema coercion.

    Returns:
        Number of records updated.
    """
    if not FORECAST_LOG_FILE.exists():
        return 0

    # Import here to avoid a circular import (binance_client → config, not eval)
    from precog_baseline_miner.data.binance_client import fetch_candles

    with _write_lock:
        text = FORECAST_LOG_FILE.read_text()

    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return 0

    records = []
    for line in lines:
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            logger.warning("Skipping malformed log line: %s", exc)

    now = datetime.now(timezone.utc)
    updated = 0

    for rec in records:
        if rec.get("realized_price_1h") is not None:
            continue  # already filled

        # Parse prediction timestamp (both v1 and v2 use the same key)
        try:
            pred_ts = datetime.fromisoformat(
                rec["prediction_ts"].replace("Z", "+00:00")
            )
        except (KeyError, ValueError) as exc:
            logger.debug("Cannot parse prediction_ts in record: %s", exc)
            continue

        eval_ts = pred_ts + timedelta(hours=1)
        if eval_ts > now:
            continue  # horizon not yet reached

        # Fetch the 1-hour window of 1-min candles from Binance
        try:
            asset = rec["asset"]
            start_ms = int(pred_ts.timestamp() * 1000)
            end_ms = int(eval_ts.timestamp() * 1000)

            candles = fetch_candles(
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
            realized_min = float(candles["low"].min())
            realized_max = float(candles["high"].max())

            rec["realized_price_1h"] = realized_price
            rec["realized_min_1h"] = realized_min
            rec["realized_max_1h"] = realized_max
            rec["ape"] = compute_ape(rec["point"], realized_price)
            rec["interval_score"] = compute_interval_score(
                rec["low"], rec["high"], realized_min, realized_max
            )
            updated += 1

        except Exception as exc:
            logger.warning(
                "Could not fill realized for asset=%s ts=%s: %s",
                rec.get("asset"),
                rec.get("prediction_ts"),
                exc,
            )

    if updated:
        with _write_lock:
            with open(FORECAST_LOG_FILE, "w") as fh:
                for rec in records:
                    fh.write(json.dumps(rec) + "\n")

        logger.info("fill_realized: updated %d record(s)", updated)

    return updated
