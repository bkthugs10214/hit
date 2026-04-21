"""
Sentiment logger.

Each sentiment fetch is appended to SENTIMENT_LOG_FILE as newline-delimited JSON.
Mirrors the pattern in eval/recorder.py: thread-safe append, silently swallows
I/O errors so a log failure never crashes the miner.

Log file location: ~/.precog_baseline/sentiment.jsonl  (configurable via env)

Record schema
-------------
{
  "logged_at":         "2026-04-19T12:00:00.000000Z",
  "asset":             "btc",
  "fear_greed_value":  62,
  "fear_greed_class":  "Greed",
  "cryptopanic_score": 0.41,
  "cp_article_count":  12,
  "reddit_score":      0.18,
  "reddit_post_count": 25,
  "combined_signal":   0.37,
  "cache_hit":         false
}
"""
import json
import logging
import threading
from datetime import datetime, timezone

from precog_baseline_miner.config import SENTIMENT_LOG_FILE
from precog_baseline_miner.data.sentiment import SentimentBundle

logger = logging.getLogger(__name__)

_write_lock = threading.Lock()


def log_sentiment(
    asset: str,
    bundle: SentimentBundle,
    combined_signal: float | None,
) -> None:
    """
    Append one sentiment record to the JSONL log.

    Silently swallows I/O errors so that a logging failure never crashes
    the miner's forward function.
    """
    fg = bundle.fear_greed
    cp = bundle.cryptopanic
    rd = bundle.reddit

    record = {
        "logged_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z",
        "asset": asset,
        "fear_greed_value": fg.value if fg else None,
        "fear_greed_class": fg.classification if fg else None,
        "cryptopanic_score": round(cp.score, 4) if cp else None,
        "cp_article_count": cp.article_count if cp else None,
        "reddit_score": round(rd.score, 4) if rd else None,
        "reddit_post_count": rd.post_count if rd else None,
        "combined_signal": round(combined_signal, 4) if combined_signal is not None else None,
        "cache_hit": fg.from_cache if fg else (rd.from_cache if rd else False),
    }

    with _write_lock:
        try:
            with open(SENTIMENT_LOG_FILE, "a") as fh:
                fh.write(json.dumps(record) + "\n")
        except Exception as exc:
            logger.error("Failed to write sentiment log: %s", exc)
