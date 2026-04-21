"""
Futures data logger.

Appends one record per asset per forward call to FUTURES_LOG_FILE as
newline-delimited JSON. Thread-safe, silently swallows I/O errors.

Log file: ~/.precog_baseline/futures.jsonl  (configurable via env)

Record schema
-------------
{
  "logged_at":       "2026-04-21T12:00:00.000000Z",
  "asset":           "btc",
  "symbol":          "BTC_USDT",
  "funding_rate":    0.0001,
  "open_interest":   109949667.0,
  "fair_price":      75500.0,
  "volume_24h":      12345.0,
  "futures_signal":  -0.1,
  "cache_hit":       false
}
"""
import json
import logging
import threading
from datetime import datetime, timezone

from precog_baseline_miner.config import FUTURES_LOG_FILE
from precog_baseline_miner.data.futures import FuturesBundle

logger = logging.getLogger(__name__)

_write_lock = threading.Lock()


def log_futures(
    asset: str,
    bundle: FuturesBundle,
    signal: float | None,
) -> None:
    """
    Append one futures record to the JSONL log.

    Silently swallows I/O errors so a logging failure never crashes the miner.
    """
    mx = bundle.mexc

    record = {
        "logged_at":      datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z",
        "asset":          asset,
        "symbol":         mx.symbol if mx else None,
        "funding_rate":   round(mx.funding_rate, 8) if mx else None,
        "open_interest":  round(mx.open_interest, 2) if mx else None,
        "fair_price":     round(mx.fair_price, 4) if mx else None,
        "volume_24h":     round(mx.volume_24h, 4) if mx else None,
        "futures_signal": round(signal, 4) if signal is not None else None,
        "cache_hit":      mx.from_cache if mx else False,
    }

    with _write_lock:
        try:
            with open(FUTURES_LOG_FILE, "a") as fh:
                fh.write(json.dumps(record) + "\n")
        except Exception as exc:
            logger.error("Failed to write futures log: %s", exc)
