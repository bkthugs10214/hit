"""
Futures data aggregator.

Fetches perpetual futures metrics (funding rate, open interest) from MEXC
for each asset. Returns a FuturesBundle — failures produce None fields and
the downstream signal degrades gracefully to momentum-only.
"""
import logging
from dataclasses import dataclass

from precog_baseline_miner.config import FUTURES_CACHE_TTL
from precog_baseline_miner.data.futures.mexc_futures import FuturesResult, fetch_mexc_futures

logger = logging.getLogger(__name__)

__all__ = ["FuturesBundle", "fetch_all_futures"]


@dataclass
class FuturesBundle:
    mexc: FuturesResult | None


def fetch_all_futures(asset: str) -> FuturesBundle:
    """
    Fetch futures metrics for the given asset.

    Currently sourced from MEXC perpetual futures (accessible from US, no key).
    Additional exchanges can be added here as new fields on FuturesBundle.
    """
    result = fetch_mexc_futures(asset, cache_ttl=FUTURES_CACHE_TTL)
    logger.debug(
        "Futures bundle for %s: funding=%s  OI=%s",
        asset,
        f"{result.funding_rate:+.6f}" if result else "N/A",
        f"{result.open_interest:,.0f}" if result else "N/A",
    )
    return FuturesBundle(mexc=result)
