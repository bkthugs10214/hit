"""
Test that forecast functions return correctly shaped, valid outputs
given normal (sufficient) candle data.
"""
import numpy as np
import pandas as pd
import pytest

from precog_baseline_miner.forecast.baseline import compute_point_forecast
from precog_baseline_miner.forecast.interval import compute_interval


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

def test_point_forecast_returns_float():
    candles = make_candles(60)
    result = compute_point_forecast(candles)
    assert isinstance(result, float)


def test_point_forecast_is_positive():
    candles = make_candles(60)
    result = compute_point_forecast(candles)
    assert result > 0


def test_point_forecast_close_to_spot():
    """With shrinkage=0.1 the forecast should stay within 1% of spot."""
    candles = make_candles(60)
    spot = float(candles["close"].iloc[-1])
    result = compute_point_forecast(candles, shrinkage=0.10)
    assert abs(result - spot) / spot < 0.01


def test_point_forecast_zero_shrinkage_equals_spot():
    """shrinkage=0 → pure persistence."""
    candles = make_candles(60)
    spot = float(candles["close"].iloc[-1])
    result = compute_point_forecast(candles, shrinkage=0.0)
    assert result == pytest.approx(spot)


# ── Interval forecast tests ───────────────────────────────────────────────────

def test_interval_returns_two_floats():
    candles = make_candles(60)
    point = compute_point_forecast(candles)
    result = compute_interval(candles, point)
    assert len(result) == 2
    lo, hi = result
    assert isinstance(lo, float)
    assert isinstance(hi, float)


def test_interval_low_less_than_high():
    candles = make_candles(60)
    point = compute_point_forecast(candles)
    lo, hi = compute_interval(candles, point)
    assert lo < hi


def test_interval_contains_point():
    """The point forecast should always lie inside the interval."""
    candles = make_candles(60)
    point = compute_point_forecast(candles)
    lo, hi = compute_interval(candles, point)
    assert lo <= point <= hi


def test_interval_both_positive():
    candles = make_candles(60)
    point = compute_point_forecast(candles)
    lo, hi = compute_interval(candles, point)
    assert lo > 0
    assert hi > 0
