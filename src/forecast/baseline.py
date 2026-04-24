"""
Baseline point forecast: momentum + optional sentiment + optional futures.

Strategy
--------
We compute a blended short/medium momentum signal and shrink it aggressively
toward zero (persistence). Optional sentiment and futures signals contribute
additional drift components, each taking a configurable weight from the
momentum budget.

Formula
-------
  momentum_drift = 0.7 × ret_5m + 0.3 × ret_15m
  drift = w_momentum × momentum_drift
        + w_sentiment × sentiment        (if available)
        + w_futures   × futures_signal   (if available)
  point = spot × (1 + k × drift)

where w_momentum = 1 - w_sentiment - w_futures (remaining budget).

This is deliberately not smart. It is meant to produce a legal, passable
baseline. Replace or extend it in forecast/ml.py once you have live data.
"""
from dataclasses import dataclass
from typing import Any

import pandas as pd

from precog_baseline_miner.config import FUTURES_WEIGHT, SENTIMENT_WEIGHT
from precog_baseline_miner.data.candles import latest_close
from precog_baseline_miner.features.returns import momentum_returns


@dataclass(frozen=True)
class ForecastResult:
    """
    Output of compute_point_forecast.

    features contains only the inputs that materially affected `point`:
      - Happy path: ret_5m, ret_15m, point_shrinkage, and — when supplied —
        sentiment_sig + sentiment_weight, futures_sig + futures_weight
      - Fallback (< 16 candles): {"point_fallback": "insufficient_candles"}

    Derived values (momentum_drift, effective weights, drift) are NOT logged:
    they are reconstructable from the inputs above.
    """
    point: float
    features: dict[str, Any]


def compute_point_forecast(
    candles: pd.DataFrame,
    shrinkage: float = 0.10,
    sentiment: float | None = None,
    sentiment_weight: float = SENTIMENT_WEIGHT,
    futures: float | None = None,
    futures_weight: float = FUTURES_WEIGHT,
) -> ForecastResult:
    """
    Compute a one-hour-ahead point forecast from OHLCV candles.

    Args:
        candles:          OHLCV DataFrame from fetch_candles(). Needs at least
                          16 rows; falls back to spot (persistence) if fewer.
        shrinkage:        dampening coefficient on raw drift. Range [0, 1].
        sentiment:        normalized sentiment signal in [-1, 1], or None.
        sentiment_weight: fraction of drift budget allocated to sentiment.
        futures:          normalized futures signal in [-1, 1], or None.
        futures_weight:   fraction of drift budget allocated to futures.

    Returns:
        ForecastResult(point, features). `point` is a positive USD price.
        `features` is the set of inputs that materially affected `point`;
        see ForecastResult docstring for exact shape per path.
    """
    spot = latest_close(candles)

    if len(candles) < 16:
        return ForecastResult(
            point=spot,
            features={"point_fallback": "insufficient_candles"},
        )

    ret_5m, ret_15m = momentum_returns(candles, short_period=5, long_period=15)
    momentum_drift = 0.7 * ret_5m + 0.3 * ret_15m

    eff_sentiment_w = sentiment_weight if sentiment is not None else 0.0
    eff_futures_w   = futures_weight   if futures   is not None else 0.0
    eff_momentum_w  = max(0.0, 1.0 - eff_sentiment_w - eff_futures_w)

    drift = (
        eff_momentum_w * momentum_drift
        + eff_sentiment_w * (sentiment or 0.0)
        + eff_futures_w   * (futures   or 0.0)
    )

    point = spot * (1.0 + shrinkage * drift)

    features: dict[str, Any] = {
        "ret_5m": ret_5m,
        "ret_15m": ret_15m,
        "point_shrinkage": shrinkage,
    }
    if sentiment is not None:
        features["sentiment_sig"] = sentiment
        features["sentiment_weight"] = sentiment_weight
    if futures is not None:
        features["futures_sig"] = futures
        features["futures_weight"] = futures_weight

    return ForecastResult(point=point, features=features)
