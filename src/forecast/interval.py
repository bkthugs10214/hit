"""
Baseline interval forecast: symmetric realized-volatility interval.

Strategy
--------
We estimate the expected hourly price move from the realized volatility of
1-minute returns (scaled by √60).  The interval is symmetric around the point
forecast and clamped to sensible bounds.

Interval scoring (from precog/validators/reward.py)
----------------------------------------------------
  score = inclusion_factor × width_factor

  inclusion_factor = fraction of actual 1s prices inside [low, high]
  width_factor     = overlap([low,high], [obs_min,obs_max]) / (high - low)

Implication: very wide intervals hurt width_factor; very narrow intervals
hurt inclusion_factor.  The clamping below targets a half-width in the range
[0.1%, 7.5%], which empirically balances the two factors for crypto.

Formula
-------
  hourly_vol = std(1-min returns) × √60
  half_width = clamp(multiplier × hourly_vol × point,
                     min=point × 0.001,
                     max=point × 0.075)
  [low, high] = [point − half, point + half]
"""
import math

import pandas as pd

from precog_baseline_miner.features.volatility import hourly_vol_estimate

# Clamp bounds (fraction of point price)
_MIN_HALF_WIDTH_PCT = 0.001   # 0.1%  — never produce a zero-width interval
_MAX_HALF_WIDTH_PCT = 0.075   # 7.5%  — 15% total; wider than this is too sloppy


def compute_interval(
    candles: pd.DataFrame,
    point: float,
    multiplier: float = 1.0,
) -> tuple[float, float]:
    """
    Compute a [low, high] interval around the point forecast.

    Args:
        candles:    OHLCV DataFrame from fetch_candles().
        point:      The point forecast value (output of compute_point_forecast).
        multiplier: Scale factor for the half-width.
                    1.0 targets ~1 hourly-std on each side.
                    Increase to widen (better inclusion, lower width_factor).

    Returns:
        (low, high) with low < high and both > 0.
        Falls back to fixed ±2% around point if fewer than 20 candles.
    """
    if len(candles) < 20:
        # Fixed-width fallback: ±2%
        margin = point * 0.02
        return point - margin, point + margin

    hourly_vol = hourly_vol_estimate(candles)
    raw_half = multiplier * hourly_vol * point

    min_half = point * _MIN_HALF_WIDTH_PCT
    max_half = point * _MAX_HALF_WIDTH_PCT
    half = max(min_half, min(raw_half, max_half))

    return point - half, point + half
