"""
Fetches OHLCV candles from the Binance-compatible public REST API.

Primary exchange: BINANCE_BASE_URL (default api.binance.com; US users set
api.binance.us). Secondary exchange: MEXC_BASE_URL (api.mexc.com) — used
automatically when the primary returns "Invalid symbol", e.g. TAOUSDT on
Binance.US. MEXC uses the identical /api/v3/klines endpoint and response format.

No authentication is required for either exchange — all endpoints used here
are public. Rate limit on Binance: 1200 requests/minute (1 weight per request).
"""
import logging

import pandas as pd
import requests

from precog_baseline_miner.config import (
    BINANCE_BASE_URL,
    BINANCE_REQUEST_TIMEOUT,
    MEXC_BASE_URL,
)
from precog_baseline_miner.miner.adapter import ASSET_SYMBOL_MAP

logger = logging.getLogger(__name__)

_KLINES_PATH = "/api/v3/klines"

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

_KEEP_COLS = ["open_time", "open", "high", "low", "close", "volume"]

# Binance error code for unknown/unlisted symbol
_INVALID_SYMBOL_CODE = -1121


def fetch_candles(
    asset: str,
    interval: str = "1m",
    limit: int = 100,
    start_ms: int | None = None,
    end_ms: int | None = None,
) -> pd.DataFrame:
    """
    Fetch OHLCV candles for a Precog asset.

    Tries the primary exchange (BINANCE_BASE_URL) first. If that exchange
    returns "Invalid symbol" (e.g. TAOUSDT on Binance.US), retries
    automatically against the secondary exchange (MEXC_BASE_URL).

    Args:
        asset:    Precog asset name (e.g. "btc", "eth", "tao_bittensor").
        interval: Klines interval string ("1m", "5m", "1h", …).
        limit:    Number of candles to return (max 1000).
        start_ms: Optional start time in Unix milliseconds.
        end_ms:   Optional end time in Unix milliseconds.

    Returns:
        DataFrame with columns: open_time (UTC), open, high, low, close, volume.

    Raises:
        KeyError:           if asset is not in ASSET_SYMBOL_MAP.
        requests.HTTPError: if both exchanges return a non-symbol error.
        requests.Timeout:   if the request exceeds BINANCE_REQUEST_TIMEOUT.
    """
    symbol = ASSET_SYMBOL_MAP[asset.lower()]
    params: dict = {"symbol": symbol, "interval": interval, "limit": limit}
    if start_ms is not None:
        params["startTime"] = start_ms
    if end_ms is not None:
        params["endTime"] = end_ms

    for base_url, label in [
        (BINANCE_BASE_URL, "primary"),
        (MEXC_BASE_URL, "MEXC fallback"),
    ]:
        url = f"{base_url}{_KLINES_PATH}"
        logger.debug("Fetching %d x %s candles for %s from %s", limit, interval, symbol, label)
        try:
            response = requests.get(url, params=params, timeout=BINANCE_REQUEST_TIMEOUT)
        except requests.Timeout:
            logger.warning("Timeout fetching %s from %s", symbol, label)
            if label == "MEXC fallback":
                raise
            continue

        # Check for "Invalid symbol" before raising — signals we should try MEXC
        if response.status_code == 400:
            try:
                body = response.json()
            except Exception:
                body = {}
            if body.get("code") == _INVALID_SYMBOL_CODE:
                logger.warning(
                    "%s: symbol %s not listed on %s — trying %s",
                    asset, symbol, label, "MEXC fallback",
                )
                continue  # retry on MEXC

        response.raise_for_status()
        raw = response.json()

        if not raw:
            logger.warning("%s returned 0 candles for %s", label, symbol)
            return _empty_candle_df()

        if label == "MEXC fallback":
            logger.info("Using MEXC candles for %s (not listed on primary exchange)", asset)

        return _parse_klines(raw)

    # Both exchanges exhausted
    raise requests.HTTPError(f"No exchange could provide candles for {symbol}")


def _parse_klines(raw: list) -> pd.DataFrame:
    df = pd.DataFrame(raw, columns=_KLINE_COLUMNS[: len(raw[0])])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    return df[_KEEP_COLS].copy()


def _empty_candle_df() -> pd.DataFrame:
    return pd.DataFrame(columns=_KEEP_COLS).astype({
        "open_time": "datetime64[ns, UTC]",
        "open":  "float64",
        "high":  "float64",
        "low":   "float64",
        "close": "float64",
        "volume": "float64",
    })
