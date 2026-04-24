"""
Phase 1 tests — forecasts.jsonl schema v2.

Covers:
  1. A v2 row written WITH a features dict round-trips with nested features.
  2. A v2 row written WITHOUT features omits the key entirely (not null).
  3. fill_realized() tolerates a mix of v1 (legacy) and v2 rows — both get
     their realized_* / ape / interval_score fields populated, and each row
     preserves its original schema shape on rewrite.
  4. Property test: the features logged by log_forecast() equal exactly the
     values returned by compute_point_forecast() ∪ compute_interval().
"""
import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from precog_baseline_miner.eval import recorder as recorder_mod
from precog_baseline_miner.eval.recorder import fill_realized, log_forecast
from precog_baseline_miner.forecast.baseline import compute_point_forecast
from precog_baseline_miner.forecast.interval import compute_interval


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def log_file(tmp_path, monkeypatch):
    """Redirect FORECAST_LOG_FILE to a pytest tmp_path for isolation."""
    path = tmp_path / "forecasts.jsonl"
    monkeypatch.setattr(recorder_mod, "FORECAST_LOG_FILE", path)
    return path


def make_candles(n: int = 60, start_price: float = 60_000.0) -> pd.DataFrame:
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


def _read(path) -> list[dict]:
    return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


# ── Case 1: v2 with features ──────────────────────────────────────────────────

def test_v2_row_with_features(log_file):
    features = {
        "ret_5m": 0.00032,
        "ret_15m": -0.00014,
        "point_shrinkage": 0.10,
        "hourly_vol": 0.015,
        "interval_multiplier": 1.0,
    }
    log_forecast(
        asset="btc",
        timestamp="2026-04-24T12:00:00.000000Z",
        spot=65_000.0, point=65_020.0, low=63_800.0, high=66_200.0,
        features=features,
    )

    rows = _read(log_file)
    assert len(rows) == 1
    row = rows[0]

    # Top-level v2 metadata
    assert row["schema_version"] == "v2"
    assert row["asset"] == "btc"
    assert row["spot"] == 65_000.0
    assert row["point"] == 65_020.0

    # Features are nested — NOT flattened into top-level keys
    assert "features" in row
    assert row["features"] == features

    # Ensure feature keys did NOT leak to the top level
    for k in features:
        assert k not in row or k == "features"


# ── Case 2: v2 without features — key is OMITTED, not null ────────────────────

def test_v2_row_without_features_omits_key(log_file):
    log_forecast(
        asset="eth",
        timestamp="2026-04-24T12:00:00.000000Z",
        spot=2328.0, point=2335.5, low=2327.0, high=2344.0,
    )

    rows = _read(log_file)
    assert len(rows) == 1
    row = rows[0]

    assert row["schema_version"] == "v2"
    assert "features" not in row, (
        "features key must be absent when not supplied — not set to null"
    )


# ── Case 3: mixed v1 / v2 fill_realized ───────────────────────────────────────

def test_fill_realized_tolerates_mixed_v1_and_v2(log_file, monkeypatch):
    """
    Seed a file with 2 v1 rows (no schema_version, no features) and 2 v2 rows,
    all with prediction_ts ≥ 1 hour ago so the backfill horizon has elapsed.
    Monkeypatch fetch_candles to avoid the network. Assert:
      - all 4 rows get realized_* / ape / interval_score populated
      - v1 rows still lack schema_version + features after rewrite
      - v2 rows keep their features dict intact
    """
    pred_ts = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime(
        "%Y-%m-%dT%H:%M:%S.%f"
    ) + "Z"

    v1_row_a = {
        "logged_at": pred_ts, "prediction_ts": pred_ts, "asset": "btc",
        "spot": 60_000.0, "point": 60_100.0, "low": 59_000.0, "high": 61_000.0,
        "realized_price_1h": None, "realized_min_1h": None,
        "realized_max_1h": None, "ape": None, "interval_score": None,
    }
    v1_row_b = {**v1_row_a, "asset": "eth", "spot": 2300.0, "point": 2305.0,
                "low": 2280.0, "high": 2330.0}
    v2_features = {
        "ret_5m": 0.0003, "ret_15m": -0.0001, "point_shrinkage": 0.10,
        "hourly_vol": 0.015, "interval_multiplier": 1.0,
    }
    v2_row_a = {**v1_row_a, "schema_version": "v2", "asset": "tao_bittensor",
                "spot": 248.0, "point": 248.9, "low": 247.0, "high": 250.8,
                "features": v2_features}
    v2_row_b = {**v2_row_a, "asset": "btc", "spot": 60_500.0, "point": 60_700.0,
                "low": 59_500.0, "high": 61_500.0}

    log_file.write_text(
        "\n".join(json.dumps(r) for r in [v1_row_a, v1_row_b, v2_row_a, v2_row_b])
        + "\n"
    )

    # Mock Binance — return a synthetic 65-row window so fill_realized can work
    fake_candles = pd.DataFrame({
        "open_time": pd.date_range("2026-01-01", periods=65, freq="1min", tz="UTC"),
        "open": [60_100.0] * 65, "high": [60_200.0] * 65,
        "low":  [60_000.0] * 65, "close": [60_150.0] * 65,
        "volume": [1.0] * 65,
    })

    def fake_fetch_candles(asset, interval="1m", limit=500,
                           start_ms=None, end_ms=None):
        return fake_candles

    import precog_baseline_miner.data.binance_client as bc
    monkeypatch.setattr(bc, "fetch_candles", fake_fetch_candles)

    updated = fill_realized()
    assert updated == 4

    rows = _read(log_file)
    assert len(rows) == 4

    # All rows got their realized fields populated
    for row in rows:
        assert row["realized_price_1h"] is not None
        assert row["realized_min_1h"] is not None
        assert row["realized_max_1h"] is not None
        assert row["ape"] is not None
        assert row["interval_score"] is not None

    # v1 rows (index 0, 1) must still lack schema_version and features
    for i in (0, 1):
        assert "schema_version" not in rows[i]
        assert "features" not in rows[i]

    # v2 rows (index 2, 3) must keep their features intact
    for i in (2, 3):
        assert rows[i]["schema_version"] == "v2"
        assert rows[i]["features"] == v2_features


# ── Case 4: property test — logged features == forecast function outputs ──────

def test_logged_features_equal_forecast_return_values(log_file):
    """
    The features logged to JSONL must be identical to the dicts returned by
    compute_point_forecast() and compute_interval(). If they ever diverge —
    e.g. someone renames a key in one place but not the other — this test
    catches it immediately.
    """
    candles = make_candles(60)
    sent_sig, fut_sig = -0.42, 0.038

    fcst = compute_point_forecast(
        candles, shrinkage=0.10,
        sentiment=sent_sig, sentiment_weight=0.15,
        futures=fut_sig,    futures_weight=0.10,
    )
    itvl = compute_interval(candles, fcst.point, multiplier=1.0)

    merged = {**fcst.features, **itvl.features}

    log_forecast(
        asset="btc",
        timestamp="2026-04-24T12:00:00.000000Z",
        spot=float(candles["close"].iloc[-1]),
        point=fcst.point, low=itvl.low, high=itvl.high,
        features=merged,
    )

    row = _read(log_file)[0]

    # Every feature from both dataclasses appears, with identical values
    for key, val in fcst.features.items():
        assert row["features"][key] == pytest.approx(val)
    for key, val in itvl.features.items():
        assert row["features"][key] == pytest.approx(val)

    # And nothing extra slipped in
    assert set(row["features"].keys()) == set(merged.keys())
