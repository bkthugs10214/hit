"""
MEXC perpetual futures client.

Fetches funding rate, open interest, fair price, and 24h volume from the
MEXC contract ticker. No authentication required — all endpoints are public.

MEXC is accessible from the US where Binance futures (fapi.binance.com)
and Bybit are geo-blocked.

Base URL: https://contract.mexc.com
Ticker endpoint: GET /api/v1/contract/ticker?symbol={SYMBOL}
"""
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import requests

from precog_baseline_miner.config import BINANCE_REQUEST_TIMEOUT, MEXC_FUTURES_BASE_URL, VERBOSE

logger = logging.getLogger(__name__)

_TICKER_PATH = "/api/v1/contract/ticker"

# Map Precog asset names → MEXC perpetual futures symbols
_ASSET_SYMBOL_MAP: dict[str, str] = {
    "btc":           "BTC_USDT",
    "eth":           "ETH_USDT",
    "tao_bittensor": "TAO_USDT",
}


@dataclass
class FuturesResult:
    symbol: str
    funding_rate: float   # current funding rate (e.g. 0.0001 = 0.01% per cycle)
    open_interest: float  # holdVol: total open contracts in quote currency (USDT)
    fair_price: float     # mark/fair price used for liquidations
    volume_24h: float     # 24-hour trading volume in contracts
    fetched_at: datetime
    from_cache: bool


# Per-asset TTL cache: symbol → (result, expiry_monotonic)
_cache: dict[str, tuple[FuturesResult, float]] = {}


def fetch_mexc_futures(asset: str, cache_ttl: int) -> FuturesResult | None:
    """
    Fetch perpetual futures metrics for an asset from MEXC.

    Returns a cached result if within TTL. Returns None on any failure or
    if the asset has no MEXC futures market.

    Args:
        asset:     Precog asset name (e.g. "btc", "eth", "tao_bittensor").
        cache_ttl: seconds to cache results before re-fetching.
    """
    symbol = _ASSET_SYMBOL_MAP.get(asset.lower())
    if symbol is None:
        logger.warning("MEXC futures: no symbol mapping for asset '%s'", asset)
        return None

    now_mono = time.monotonic()
    if symbol in _cache:
        cached_result, expiry = _cache[symbol]
        if now_mono < expiry:
            if VERBOSE:
                logger.debug("MEXC futures cache hit for %s: funding=%+.6f",
                             symbol, cached_result.funding_rate)
            return FuturesResult(
                symbol=cached_result.symbol,
                funding_rate=cached_result.funding_rate,
                open_interest=cached_result.open_interest,
                fair_price=cached_result.fair_price,
                volume_24h=cached_result.volume_24h,
                fetched_at=cached_result.fetched_at,
                from_cache=True,
            )

    logger.debug("Fetching MEXC futures ticker for %s", symbol)
    try:
        resp = requests.get(
            f"{MEXC_FUTURES_BASE_URL}{_TICKER_PATH}",
            params={"symbol": symbol},
            timeout=BINANCE_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        raw = resp.json()

        if VERBOSE:
            logger.debug("MEXC futures raw payload for %s: %s", symbol, raw)

        if not raw.get("success"):
            logger.warning("MEXC futures: non-success response for %s: %s", symbol, raw)
            return None

        data = raw["data"]
        result = FuturesResult(
            symbol=symbol,
            funding_rate=float(data["fundingRate"]),
            open_interest=float(data["holdVol"]),
            fair_price=float(data["fairPrice"]),
            volume_24h=float(data["volume24"]),
            fetched_at=datetime.now(timezone.utc),
            from_cache=False,
        )
        _cache[symbol] = (result, now_mono + cache_ttl)
        logger.info(
            "MEXC futures %s: funding=%+.6f  OI=%.0f  fair=$%.2f",
            symbol, result.funding_rate, result.open_interest, result.fair_price,
        )
        return result

    except Exception as exc:
        logger.warning("MEXC futures fetch failed for %s: %s", symbol, exc)
        return None
