"""
Fear & Greed Index fetcher — alternative.me public API.

No authentication required. Updates once daily; we cache the result
for SENTIMENT_CACHE_TTL seconds (default 300) to avoid hammering the endpoint
on every forward pass.

Endpoint: https://api.alternative.me/fng/?limit=1
"""
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import requests

from precog_baseline_miner.config import SENTIMENT_REQUEST_TIMEOUT, VERBOSE

logger = logging.getLogger(__name__)

_FNG_URL = "https://api.alternative.me/fng/?limit=1"


@dataclass
class FearGreedResult:
    value: int           # 0 (extreme fear) – 100 (extreme greed)
    classification: str  # e.g. "Greed", "Fear", "Neutral"
    fetched_at: datetime
    from_cache: bool


# Module-level TTL cache: (result, expiry_monotonic)
_cache: tuple[FearGreedResult, float] | None = None


def fetch_fear_greed(cache_ttl: int) -> FearGreedResult | None:
    """
    Fetch the current Fear & Greed Index value.

    Returns a cached result if within TTL. Returns None on any failure.

    Args:
        cache_ttl: seconds to cache the result before re-fetching.
    """
    global _cache

    now_mono = time.monotonic()
    if _cache is not None:
        cached_result, expiry = _cache
        if now_mono < expiry:
            if VERBOSE:
                logger.debug(
                    "F&G cache hit: value=%d (%s)",
                    cached_result.value,
                    cached_result.classification,
                )
            return FearGreedResult(
                value=cached_result.value,
                classification=cached_result.classification,
                fetched_at=cached_result.fetched_at,
                from_cache=True,
            )

    logger.debug("Fetching Fear & Greed Index from alternative.me")
    try:
        resp = requests.get(_FNG_URL, timeout=SENTIMENT_REQUEST_TIMEOUT)
        resp.raise_for_status()
        raw = resp.json()

        if VERBOSE:
            logger.debug("F&G raw payload: %s", raw)

        entry = raw["data"][0]
        result = FearGreedResult(
            value=int(entry["value"]),
            classification=entry["value_classification"],
            fetched_at=datetime.now(timezone.utc),
            from_cache=False,
        )
        _cache = (result, now_mono + cache_ttl)
        logger.info("F&G fetched: value=%d (%s)", result.value, result.classification)
        return result

    except Exception as exc:
        logger.warning("Fear & Greed fetch failed: %s", exc)
        return None
