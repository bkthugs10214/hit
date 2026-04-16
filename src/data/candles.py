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
