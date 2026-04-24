"""
Test that forecast functions return correctly shaped, valid outputs
given normal (sufficient) candle data.
"""
import numpy as np
import pandas as pd
import pytest

from precog_baseline_miner.forecast.baseline import (
    ForecastResult,
    compute_point_forecast,
)
from precog_baseline_miner.forecast.interval import (
    IntervalResult,
    compute_interval,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_candles(n: int = 60, start_price: float = 60_000.0) -> pd.DataFrame:
    """Synthetic 1-min OHLCV candles with a gentle upward random walk."""
    rng = np.random.default_rng(seed=42)
    returns = rng.normal(0, 0.001, n)
    prices = start_price * np.cumprod(1 + returns)
    return pd.DataFrame({
        "open_time": pd.date_range("2024-01-01", periods=n, freq="1min", tz="UTC"),
        "open":   prices,
        "high":   prices * (1 + abs(rng.normal(0, 0.0005, n))),
        "low":    prices * (1 - abs(rng.normal(0, 0.0005, n))),
        "close":  prices,
        "volume": rng.uniform(1, 10, n),
    })


# ── Point forecast tests ──────────────────────────────────────────────────────

def test_point_forecast_returns_result_dataclass():
    candles = make_candles(60)
    result = compute_point_forecast(candles)
    assert isinstance(result, ForecastResult)
    assert isinstance(result.point, float)
    assert isinstance(result.features, dict)


def test_point_forecast_is_positive():
    candles = make_candles(60)
    result = compute_point_forecast(candles)
    assert result.point > 0


def test_point_forecast_close_to_spot():
    """With shrinkage=0.1 the forecast should stay within 1% of spot."""
    candles = make_candles(60)
    spot = float(candles["close"].iloc[-1])
    result = compute_point_forecast(candles, shrinkage=0.10)
    assert abs(result.point - spot) / spot < 0.01


def test_point_forecast_zero_shrinkage_equals_spot():
    """shrinkage=0 → pure persistence."""
    candles = make_candles(60)
    spot = float(candles["close"].iloc[-1])
    result = compute_point_forecast(candles, shrinkage=0.0)
    assert result.point == pytest.approx(spot)


def test_point_forecast_features_contain_momentum_inputs():
    """Happy path: ret_5m and ret_15m are present — they materially affect point."""
    candles = make_candles(60)
    result = compute_point_forecast(candles)
    assert "ret_5m" in result.features
    assert "ret_15m" in result.features
    assert "point_shrinkage" in result.features


def test_point_forecast_features_omit_sentiment_when_none():
    """When sentiment=None, sentiment_sig/weight must not appear in features."""
    candles = make_candles(60)
    result = compute_point_forecast(candles, sentiment=None, futures=None)
    assert "sentiment_sig" not in result.features
    assert "sentiment_weight" not in result.features
    assert "futures_sig" not in result.features
    assert "futures_weight" not in result.features


def test_point_forecast_features_include_supplied_signals():
    """When sentiment and futures are supplied, both sig+weight are logged."""
    candles = make_candles(60)
    result = compute_point_forecast(
        candles, sentiment=-0.42, sentiment_weight=0.15,
        futures=0.038, futures_weight=0.10,
    )
    assert result.features["sentiment_sig"] == pytest.approx(-0.42)
    assert result.features["sentiment_weight"] == pytest.approx(0.15)
    assert result.features["futures_sig"] == pytest.approx(0.038)
    assert result.features["futures_weight"] == pytest.approx(0.10)


# ── Interval forecast tests ───────────────────────────────────────────────────

def test_interval_returns_result_dataclass():
    candles = make_candles(60)
    fcst = compute_point_forecast(candles)
    result = compute_interval(candles, fcst.point)
    assert isinstance(result, IntervalResult)
    assert isinstance(result.low, float)
    assert isinstance(result.high, float)
    assert isinstance(result.features, dict)


def test_interval_low_less_than_high():
    candles = make_candles(60)
    fcst = compute_point_forecast(candles)
    result = compute_interval(candles, fcst.point)
    assert result.low < result.high


def test_interval_contains_point():
    """The point forecast should always lie inside the interval."""
    candles = make_candles(60)
    fcst = compute_point_forecast(candles)
    result = compute_interval(candles, fcst.point)
    assert result.low <= fcst.point <= result.high


def test_interval_both_positive():
    candles = make_candles(60)
    fcst = compute_point_forecast(candles)
    result = compute_interval(candles, fcst.point)
    assert result.low > 0
    assert result.high > 0


def test_interval_features_contain_vol_and_multiplier():
    """Happy path: hourly_vol and interval_multiplier are both present."""
    candles = make_candles(60)
    fcst = compute_point_forecast(candles)
    result = compute_interval(candles, fcst.point, multiplier=1.0)
    assert "hourly_vol" in result.features
    assert "interval_multiplier" in result.features
    assert result.features["interval_multiplier"] == pytest.approx(1.0)
