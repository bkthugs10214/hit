"""
Baseline point forecast: momentum + heavy shrinkage.

Strategy
--------
We compute a blended short/medium momentum signal and then shrink it
aggressively toward zero (persistence).  The intuition is:

  - Raw momentum over 5–15 minutes has very low predictive power at a
    one-hour horizon for BTC.
  - A small shrinkage factor (k=0.10) means the forecast only moves 10% of
    what the raw momentum would suggest.
  - The result is a forecast very close to the current price — stable and
    hard to beat badly in absolute APE terms.

Formula
-------
  drift  = 0.7 × ret_5m + 0.3 × ret_15m
  point  = spot × (1 + k × drift)

This is deliberately not smart.  It is meant to produce a legal, passable
baseline.  Replace or extend it in forecast/ml.py once you have live data.
"""
import pandas as pd

from precog_baseline_miner.config import SENTIMENT_WEIGHT
from precog_baseline_miner.data.candles import latest_close
from precog_baseline_miner.features.returns import momentum_returns


def compute_point_forecast(
    candles: pd.DataFrame,
    shrinkage: float = 0.10,
    sentiment: float | None = None,
    sentiment_weight: float = SENTIMENT_WEIGHT,
) -> float:
    """
    Compute a one-hour-ahead point forecast from OHLCV candles.

    Args:
        candles:          OHLCV DataFrame from fetch_candles().
                          Needs at least 16 rows for momentum; falls back to
                          spot (persistence) if fewer rows are available.
        shrinkage:        dampening coefficient applied to the raw momentum drift.
                          Range [0, 1].  Default 0.10 is very conservative.
        sentiment:        optional normalized sentiment signal in [-1, 1].
                          None disables sentiment blending (momentum-only).
        sentiment_weight: fraction of drift budget allocated to sentiment.
                          Remaining (1 - sentiment_weight) goes to momentum.

    Returns:
        Predicted USD price one hour from now (positive float).
    """
    spot = latest_close(candles)

    if len(candles) < 16:
        # Persistence fallback: predict current spot
        return spot

    ret_5m, ret_15m = momentum_returns(candles, short_period=5, long_period=15)
    momentum_drift = 0.7 * ret_5m + 0.3 * ret_15m

    if sentiment is not None:
        momentum_blend = 1.0 - sentiment_weight
        drift = momentum_blend * momentum_drift + sentiment_weight * sentiment
    else:
        drift = momentum_drift

    return spot * (1.0 + shrinkage * drift)
