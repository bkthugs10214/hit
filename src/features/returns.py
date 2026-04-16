"""
Momentum return features derived from closing prices.

We use two lookback windows:
  - short (5 bars)  — captures recent momentum
  - long  (15 bars) — captures medium-term trend

Both are 1-minute bars, so the windows are ~5 min and ~15 min.
Returns are expressed as fractions (e.g. 0.001 = +0.1%).
"""
import pandas as pd


def momentum_returns(
    candles: pd.DataFrame,
    short_period: int = 5,
    long_period: int = 15,
) -> tuple[float, float]:
    """
    Compute short-term and medium-term momentum returns.

    Args:
        candles:      OHLCV DataFrame — must have a "close" column.
        short_period: lookback in bars for the short return (default 5 min).
        long_period:  lookback in bars for the long return (default 15 min).

    Returns:
        (ret_short, ret_long) as fractions.
        Both are 0.0 if the DataFrame does not have enough rows.
    """
    close = candles["close"]
    if len(close) < long_period + 1:
        return 0.0, 0.0

    ret_short = float(close.iloc[-1] / close.iloc[-short_period] - 1)
    ret_long = float(close.iloc[-1] / close.iloc[-long_period] - 1)
    return ret_short, ret_long
