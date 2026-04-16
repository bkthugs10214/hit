"""
Mapping between Precog asset names and exchange trading symbols.
Also provides a fallback that uses the CoinMetrics (cm) data client
when Binance is unavailable.
"""
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # CMData is only available inside the Precog environment
    pass

# Precog asset name → Binance spot symbol
# If Binance ever renames or delists a symbol, update this map.
ASSET_SYMBOL_MAP: dict[str, str] = {
    "btc":           "BTCUSDT",
    "eth":           "ETHUSDT",
    "tao_bittensor": "TAOUSDT",
}


def cm_fallback(asset: str, cm) -> float:
    """
    Fetch the latest USD price for an asset using the CoinMetrics data client.

    Used when Binance is unreachable or the symbol is delisted. The `cm`
    argument is the CMData instance injected by the Precog miner framework.

    Args:
        asset: Precog asset name (e.g. "btc", "eth", "tao_bittensor")
        cm:    CMData instance (precog.utils.cm_data.CMData)

    Returns:
        Latest reference rate in USD as a float

    Raises:
        ValueError: if CMData returns no data for the asset
    """
    now = datetime.now(timezone.utc)
    start = (now - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%S.000000Z")
    end = now.strftime("%Y-%m-%dT%H:%M:%S.000000Z")

    df = cm.get_CM_ReferenceRate(
        assets=[asset],
        start=start,
        end=end,
        frequency="1s",
    )

    if df is None or df.empty:
        raise ValueError(f"CoinMetrics returned no data for asset '{asset}'")

    return float(df["ReferenceRateUSD"].iloc[-1])
