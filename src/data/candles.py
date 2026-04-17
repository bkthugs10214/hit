"""
Utility helpers for working with OHLCV candle DataFrames.
"""
import pandas as pd


def latest_close(candles: pd.DataFrame) -> float:
    """Return the most recent closing price."""
    return float(candles["close"].iloc[-1])


def candles_are_valid(candles: pd.DataFrame, min_rows: int = 16) -> bool:
    """
    Return True if the DataFrame has enough rows and no NaN close prices.

    Args:
        candles:  OHLCV DataFrame from fetch_candles()
        min_rows: minimum number of rows required
    """
    if len(candles) < min_rows:
        return False
    if candles["close"].isna().any():
        return False
    return True


def binance_snapshot(candles: pd.DataFrame) -> dict:
    """
    Summarise a Binance OHLCV DataFrame into a compact loggable dict.

    Computes the key derived features that drive the baseline forecast,
    so they can be stored alongside the forecast output for later analysis.

    Returns:
        Dict with keys:
          ret_5m, ret_15m, ret_60m  — momentum returns at three horizons (None if insufficient data)
          rvol_1m                   — std of 1-min pct returns (None if < 5 rows)
          volume_60m                — sum of volume over last 60 candles
          vwap_60m                  — volume-weighted avg price over last 60 candles
          n_candles                 — total number of candles available
    """
    close = candles["close"]
    vol   = candles["volume"]
    n     = len(close)

    def _ret(lookback: int) -> float | None:
        if n < lookback + 1:
            return None
        return float(close.iloc[-1] / close.iloc[-lookback] - 1)

    rets  = close.pct_change().dropna()
    rvol  = float(rets.std()) if len(rets) >= 5 else None

    # Volume and VWAP over the last 60 candles (or fewer if not available)
    w = min(60, n)
    vol_w  = vol.iloc[-w:]
    vol_sum = float(vol_w.sum())

    if vol_sum > 0:
        typical = (candles["high"] + candles["low"] + candles["close"]) / 3
        vwap = float((typical.iloc[-w:] * vol_w).sum() / vol_sum)
    else:
        vwap = None

    return {
        "ret_5m":     _ret(5),
        "ret_15m":    _ret(15),
        "ret_60m":    _ret(60),
        "rvol_1m":    rvol,
        "volume_60m": vol_sum,
        "vwap_60m":   vwap,
        "n_candles":  n,
    }
