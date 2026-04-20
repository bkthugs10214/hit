"""
CryptoPanic news sentiment fetcher.

Requires a free API key set via CRYPTOPANIC_API_KEY env var.
If the key is absent, all calls return None immediately (disabled).

Scoring: (positive votes - negative votes) / total abs votes across returned
articles, normalized to [-1, 1].

Endpoint: https://cryptopanic.com/api/v1/posts/
Free tier: 5 requests/minute.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import requests

from precog_baseline_miner.config import CRYPTOPANIC_API_KEY, SENTIMENT_REQUEST_TIMEOUT, VERBOSE

logger = logging.getLogger(__name__)

_CP_URL = "https://cryptopanic.com/api/v1/posts/"

# Map Precog asset names → CryptoPanic currency codes
_ASSET_CURRENCY_MAP: dict[str, str] = {
    "btc": "BTC",
    "eth": "ETH",
    "tao_bittensor": "TAO",
}


@dataclass
class CryptoPanicResult:
    score: float         # normalized [-1, 1]; positive = bullish sentiment
    article_count: int   # number of articles scored
    fetched_at: datetime


def fetch_cryptopanic(asset: str) -> CryptoPanicResult | None:
    """
    Fetch news sentiment for an asset from CryptoPanic.

    Returns None if API key is absent, asset mapping is unknown,
    no articles are returned, or the request fails.
    """
    if not CRYPTOPANIC_API_KEY:
        logger.debug("CryptoPanic disabled (CRYPTOPANIC_API_KEY not set)")
        return None

    currency = _ASSET_CURRENCY_MAP.get(asset.lower())
    if currency is None:
        logger.warning("CryptoPanic: no currency mapping for asset '%s'", asset)
        return None

    logger.debug("Fetching CryptoPanic sentiment for %s (%s)", asset, currency)
    try:
        resp = requests.get(
            _CP_URL,
            params={
                "auth_token": CRYPTOPANIC_API_KEY,
                "currencies": currency,
                "kind": "news",
                "filter": "hot",
            },
            timeout=SENTIMENT_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        raw = resp.json()

        if VERBOSE:
            logger.debug("CryptoPanic raw payload for %s: %s", asset, raw)

        results = raw.get("results", [])
        if not results:
            logger.warning("CryptoPanic returned 0 articles for %s", asset)
            return None

        total_pos = 0
        total_neg = 0
        for article in results:
            votes = article.get("votes", {})
            pos = votes.get("positive", 0)
            neg = votes.get("negative", 0)
            total_pos += pos
            total_neg += neg
            if VERBOSE:
                logger.debug(
                    "  article=%r  pos=%d neg=%d",
                    article.get("title", "")[:60],
                    pos,
                    neg,
                )

        total_abs = total_pos + total_neg
        score = (total_pos - total_neg) / total_abs if total_abs > 0 else 0.0

        result = CryptoPanicResult(
            score=round(score, 4),
            article_count=len(results),
            fetched_at=datetime.now(timezone.utc),
        )
        logger.info(
            "CryptoPanic %s: score=%.3f from %d articles",
            asset,
            score,
            len(results),
        )
        return result

    except Exception as exc:
        logger.warning("CryptoPanic fetch failed for %s: %s", asset, exc)
        return None
