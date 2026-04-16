"""
Fetches OHLCV candles from the Binance public REST API.

No authentication is required — all endpoints used here are public.
Rate limit: 1200 requests/minute on the weight system; a single klines
request costs 1 weight, so even polling every 5 s is well within limits.

Binance klines docs:
  https://binance-docs.github.io/apidocs/spot/en/#kline-candlestick-data
"""
import logging

import pandas as pd
import requests

from precog_baseline_miner.config import BINANCE_BASE_URL, BINANCE_REQUEST_TIMEOUT
from precog_baseline_miner.miner.adapter import ASSET_SYMBOL_MAP

logger = logging.getLogger(__name__)

_KLINES_ENDPOINT = f"{BINANCE_BASE_URL}/api/v3/klines"

# Binance klines API returns a list of lists; these are the column names.
_KLINE_COLUMNS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "trades",
    "taker_buy_base",
    "taker_buy_quote",
    "ignore",
]

# Columns we keep after parsing
_KEEP_COLS = ["open_time", "open", "high", "low", "close", "volume"]


def fetch_candles(
    asset: str,
    interval: str = "1m",
    limit: int = 100,
    start_ms: int | None = None,
    end_ms: int | None = None,
) -> pd.DataFrame:
    """
    Fetch OHLCV candles for a Precog asset from Binance.

    Args:
        asset:    Precog asset name (e.g. "btc", "eth", "tao_bittensor").
                  Must be a key in ASSET_SYMBOL_MAP.
        interval: Binance interval string ("1m", "5m", "1h", …).
        limit:    Number of candles to return (max 1000).
        start_ms: Optional start time in Unix milliseconds.
        end_ms:   Optional end time in Unix milliseconds.

    Returns:
        DataFrame with columns: open_time (UTC), open, high, low, close, volume.
        All price/volume columns are float64.
        open_time is a timezone-aware UTC datetime.

    Raises:
        KeyError:              if `asset` is not in ASSET_SYMBOL_MAP.
        requests.HTTPError:    if Binance returns a 4xx/5xx status.
        requests.Timeout:      if the request exceeds BINANCE_REQUEST_TIMEOUT.
    """
    symbol = ASSET_SYMBOL_MAP[asset.lower()]
    params: dict = {"symbol": symbol, "interval": interval, "limit": limit}
    if start_ms is not None:
        params["startTime"] = start_ms
    if end_ms is not None:
        params["endTime"] = end_ms

    logger.debug("Fetching %d x %s candles for %s", limit, interval, symbol)
    response = requests.get(
        _KLINES_ENDPOINT,
        params=params,
        timeout=BINANCE_REQUEST_TIMEOUT,
    )
    response.raise_for_status()

    raw = response.json()
    if not raw:
        logger.warning("Binance returned 0 candles for %s", symbol)
        return _empty_candle_df()

    df = pd.DataFrame(raw, columns=_KLINE_COLUMNS)

    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)

    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)

    return df[_KEEP_COLS].copy()


def _empty_candle_df() -> pd.DataFrame:
    """Return an empty DataFrame with the expected candle schema."""
    return pd.DataFrame(columns=_KEEP_COLS).astype({
        "open_time": "datetime64[ns, UTC]",
        "open":  "float64",
        "high":  "float64",
        "low":   "float64",
        "close": "float64",
        "volume": "float64",
    })
