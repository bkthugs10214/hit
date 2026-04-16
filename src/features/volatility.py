"""
Realized volatility features.

We estimate hourly volatility by:
  1. Computing 1-minute percentage returns over the available history.
  2. Taking the standard deviation of those returns (= 1-min realized vol).
  3. Scaling by sqrt(60) to project to a 1-hour horizon.

This follows the standard square-root-of-time rule under i.i.d. returns.
"""
import math

import pandas as pd

_DEFAULT_VOL = 0.001  # 0.1% per minute — used when data is insufficient


def realized_vol_1m(candles: pd.DataFrame) -> float:
    """
    Compute the standard deviation of 1-minute percentage returns.

    Args:
        candles: OHLCV DataFrame with at least 5 rows.

    Returns:
        Realized vol as a fraction (e.g. 0.002 = 0.2% per minute).
        Returns _DEFAULT_VOL if there are fewer than 5 rows or std is 0.
    """
    close = candles["close"]
    if len(close) < 5:
        return _DEFAULT_VOL

    rets = close.pct_change().dropna()
    std = float(rets.std())
    return std if std > 1e-10 else _DEFAULT_VOL


def hourly_vol_estimate(candles: pd.DataFrame) -> float:
    """
    Scale 1-minute realized vol to a 1-hour estimate via sqrt(60).

    Returns:
        Expected fractional price move over 1 hour
        (e.g. 0.015 = 1.5% expected move).
    """
    return realized_vol_1m(candles) * math.sqrt(60)
