"""
Sentiment data aggregator.

Fetches all configured sentiment sources for an asset and bundles the results.
Sources fail independently — a failed source is None in the bundle; the
downstream signal function degrades gracefully to whatever is available.
"""
import logging
from dataclasses import dataclass

from precog_baseline_miner.config import SENTIMENT_CACHE_TTL
from precog_baseline_miner.data.sentiment.cryptopanic import CryptoPanicResult, fetch_cryptopanic
from precog_baseline_miner.data.sentiment.fear_greed import FearGreedResult, fetch_fear_greed

logger = logging.getLogger(__name__)

__all__ = ["SentimentBundle", "fetch_all_sentiment"]


@dataclass
class SentimentBundle:
    fear_greed: FearGreedResult | None
    cryptopanic: CryptoPanicResult | None


def fetch_all_sentiment(asset: str) -> SentimentBundle:
    """
    Fetch all sentiment sources for the given asset.

    Fear & Greed is asset-agnostic (macro crypto mood) and TTL-cached.
    CryptoPanic is per-asset. Both calls are independent.
    """
    fg = fetch_fear_greed(cache_ttl=SENTIMENT_CACHE_TTL)
    cp = fetch_cryptopanic(asset)

    logger.debug(
        "Sentiment bundle for %s: F&G=%s  CP=%s",
        asset,
        fg.value if fg else "N/A",
        f"{cp.score:.3f}" if cp else "N/A",
    )
    return SentimentBundle(fear_greed=fg, cryptopanic=cp)
