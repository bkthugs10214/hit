"""
Test that interval clamping rules hold.

The interval is scored by inclusion_factor × width_factor.
We clamp the half-width to [0.1%, 7.5%] of the point price so:
  - We always have a non-degenerate interval (score > 0)
  - We never produce an absurdly wide interval that kills the width factor
"""
import numpy as np
import pandas as pd
import pytest

from precog_baseline_miner.forecast.interval import (
    _MAX_HALF_WIDTH_PCT,
    _MIN_HALF_WIDTH_PCT,
    compute_interval,
)


def make_candles(n: int = 60, vol: float = 0.001) -> pd.DataFrame:
    rng = np.random.default_rng(seed=7)
    returns = rng.normal(0, vol, n)
    prices = 60_000.0 * np.cumprod(1 + returns)
    return pd.DataFrame({
        "open_time": pd.date_range("2024-01-01", periods=n, freq="1min", tz="UTC"),
        "open":  prices,
        "high":  prices * 1.001,
        "low":   prices * 0.999,
        "close": prices,
        "volume": np.ones(n),
    })


def make_flat_candles(n: int = 60) -> pd.DataFrame:
    """All closes identical — realized vol is 0, tests the floor clamp."""
    prices = np.full(n, 60_000.0)
    return pd.DataFrame({
        "open_time": pd.date_range("2024-01-01", periods=n, freq="1min", tz="UTC"),
        "open":  prices,
        "high":  prices,
        "low":   prices,
        "close": prices,
        "volume": np.ones(n),
    })


def make_high_vol_candles(n: int = 60) -> pd.DataFrame:
    """Very high volatility — tests the ceiling clamp."""
    rng = np.random.default_rng(seed=13)
    returns = rng.normal(0, 0.05, n)  # 5% per minute = extreme
    prices = 60_000.0 * np.cumprod(1 + returns)
    return pd.DataFrame({
        "open_time": pd.date_range("2024-01-01", periods=n, freq="1min", tz="UTC"),
        "open":  prices,
        "high":  prices * 1.05,
        "low":   prices * 0.95,
        "close": prices,
        "volume": np.ones(n),
    })


POINT = 60_000.0


def test_interval_min_width_normal():
    """Half-width >= MIN_HALF_WIDTH_PCT for normal data."""
    candles = make_candles(60)
    result = compute_interval(candles, POINT)
    half = (result.high - result.low) / 2
    assert half / POINT >= _MIN_HALF_WIDTH_PCT - 1e-10


def test_interval_max_width_high_vol():
    """Half-width <= MAX_HALF_WIDTH_PCT even for extreme volatility."""
    candles = make_high_vol_candles(60)
    result = compute_interval(candles, POINT)
    half = (result.high - result.low) / 2
    assert half / POINT <= _MAX_HALF_WIDTH_PCT + 1e-10


def test_interval_floor_on_zero_vol():
    """Flat prices → realized vol is 0 → floor clamp kicks in."""
    candles = make_flat_candles(60)
    result = compute_interval(candles, POINT)
    half = (result.high - result.low) / 2
    assert half / POINT >= _MIN_HALF_WIDTH_PCT - 1e-10


def test_interval_symmetric():
    """Interval should be symmetric around the point."""
    candles = make_candles(60)
    result = compute_interval(candles, POINT)
    assert abs((POINT - result.low) - (result.high - POINT)) < 1e-6


def test_interval_wider_with_larger_multiplier():
    """Increasing multiplier should produce a wider interval (up to the cap)."""
    candles = make_candles(60, vol=0.001)
    r1 = compute_interval(candles, POINT, multiplier=0.5)
    r2 = compute_interval(candles, POINT, multiplier=2.0)
    # Could hit the ceiling with multiplier=2, but should be >= multiplier=0.5
    assert (r2.high - r2.low) >= (r1.high - r1.low) - 1e-6
