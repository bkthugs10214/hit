"""
Test fallback behavior when data is insufficient or unavailable.

The miner must never crash the forward function — it should degrade
gracefully to persistence or fixed-width intervals.
"""
import numpy as np
import pandas as pd
import pytest

from precog_baseline_miner.forecast.baseline import compute_point_forecast
from precog_baseline_miner.forecast.interval import compute_interval


# ── Fixture helpers ───────────────────────────────────────────────────────────

def empty_candles() -> pd.DataFrame:
    return pd.DataFrame(
        columns=["open_time", "open", "high", "low", "close", "volume"]
    )


def short_candles(n: int, price: float = 60_000.0) -> pd.DataFrame:
    prices = [price] * n
    return pd.DataFrame({
        "open_time": pd.date_range("2024-01-01", periods=n, freq="1min", tz="UTC"),
        "open":   prices,
        "high":   [p * 1.001 for p in prices],
        "low":    [p * 0.999 for p in prices],
        "close":  prices,
        "volume": [1.0] * n,
    })


# ── Point forecast fallbacks ──────────────────────────────────────────────────

def test_point_forecast_persistence_on_short_data():
    """< 16 candles → fall back to spot (persistence), no exception."""
    candles = short_candles(5)
    result = compute_point_forecast(candles)
    assert result == pytest.approx(60_000.0)


def test_point_forecast_persistence_on_exactly_15_candles():
    """Boundary: exactly 15 candles → persistence (needs 16 for momentum)."""
    candles = short_candles(15)
    result = compute_point_forecast(candles)
    assert result == pytest.approx(60_000.0)


def test_point_forecast_uses_momentum_on_16_candles():
    """Boundary: 16 candles → momentum path is taken (no exception)."""
    candles = short_candles(16)
    result = compute_point_forecast(candles)
    assert isinstance(result, float)
    assert result > 0


def test_point_forecast_empty_raises():
    """Empty DataFrame has no iloc[-1], so IndexError is expected.
    Callers (forward_custom.py) must catch this and use a fallback."""
    candles = empty_candles()
    with pytest.raises((IndexError, KeyError)):
        compute_point_forecast(candles)


# ── Interval forecast fallbacks ───────────────────────────────────────────────

def test_interval_fixed_fallback_on_short_data():
    """< 20 candles → fixed ±2% interval, no exception."""
    candles = short_candles(5)
    point = 60_000.0
    lo, hi = compute_interval(candles, point)
    assert lo == pytest.approx(60_000.0 * 0.98, rel=1e-6)
    assert hi == pytest.approx(60_000.0 * 1.02, rel=1e-6)


def test_interval_fixed_fallback_on_exactly_19_candles():
    """Boundary: exactly 19 candles → fixed fallback."""
    candles = short_candles(19)
    point = 60_000.0
    lo, hi = compute_interval(candles, point)
    assert lo == pytest.approx(60_000.0 * 0.98, rel=1e-6)
    assert hi == pytest.approx(60_000.0 * 1.02, rel=1e-6)


def test_interval_uses_vol_on_20_candles():
    """Boundary: 20 candles → vol path is taken, result is valid."""
    candles = short_candles(20)
    point = 60_000.0
    lo, hi = compute_interval(candles, point)
    assert lo < hi
    assert lo > 0


# ── Metrics sanity ────────────────────────────────────────────────────────────

def test_ape_zero_for_perfect_prediction():
    from precog_baseline_miner.eval.metrics import ape
    assert ape(100.0, 100.0) == pytest.approx(0.0)


def test_ape_handles_zero_actual():
    from precog_baseline_miner.eval.metrics import ape
    assert ape(100.0, 0.0) == float("inf")


def test_interval_score_perfect():
    """Predicted interval == observed range → score should be > 0."""
    from precog_baseline_miner.eval.metrics import interval_score
    score = interval_score(64_000, 66_000, 64_000, 66_000)
    assert score > 0


def test_interval_score_no_overlap():
    """Predicted interval entirely above observed range → score = 0."""
    from precog_baseline_miner.eval.metrics import interval_score
    score = interval_score(70_000, 72_000, 60_000, 65_000)
    assert score == pytest.approx(0.0)
