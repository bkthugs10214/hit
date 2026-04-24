# Tests

All tests are synchronous `pytest` tests with no network dependencies (Binance/Reddit/MEXC are mocked or unused). Run with:

```bash
source .venv/bin/activate
python -m pytest tests/ -q
```

## Inventory

### `test_forecast_shapes.py` — 12 tests
Return-type and happy-path shape checks for `compute_point_forecast` and `compute_interval`.

| Test | Asserts |
|---|---|
| `test_point_forecast_returns_result_dataclass` | returns `ForecastResult(point: float, features: dict)` |
| `test_point_forecast_is_positive` | `result.point > 0` |
| `test_point_forecast_close_to_spot` | within 1% of spot at `shrinkage=0.10` |
| `test_point_forecast_zero_shrinkage_equals_spot` | `shrinkage=0` → pure persistence |
| `test_point_forecast_features_contain_momentum_inputs` | happy path has `ret_5m`, `ret_15m`, `point_shrinkage` |
| `test_point_forecast_features_omit_sentiment_when_none` | absent sentiment/futures → keys absent, not null |
| `test_point_forecast_features_include_supplied_signals` | supplied sentiment/futures → both sig+weight logged |
| `test_interval_returns_result_dataclass` | returns `IntervalResult(low, high, features)` |
| `test_interval_low_less_than_high` | `low < high` |
| `test_interval_contains_point` | `low ≤ point ≤ high` |
| `test_interval_both_positive` | both bounds > 0 |
| `test_interval_features_contain_vol_and_multiplier` | happy path has `hourly_vol`, `interval_multiplier` |

### `test_interval_validity.py` — 5 tests
Clamp-rule invariants for `compute_interval`.

| Test | Asserts |
|---|---|
| `test_interval_min_width_normal` | half-width ≥ 0.1% of point for normal vol |
| `test_interval_max_width_high_vol` | half-width ≤ 7.5% of point even for 5%/min vol |
| `test_interval_floor_on_zero_vol` | flat prices trigger the floor clamp |
| `test_interval_symmetric` | interval is symmetric around point |
| `test_interval_wider_with_larger_multiplier` | multiplier scales width up to the cap |

### `test_fallbacks.py` — 13 tests
Graceful-degradation paths and metrics sanity.

| Test | Asserts |
|---|---|
| `test_point_forecast_persistence_on_short_data` | < 16 candles → spot |
| `test_point_forecast_persistence_on_exactly_15_candles` | boundary: 15 → spot |
| `test_point_forecast_uses_momentum_on_16_candles` | boundary: 16 → momentum path |
| `test_point_forecast_fallback_marker_in_features` | fallback features dict = `{"point_fallback": ...}` only |
| `test_point_forecast_empty_raises` | empty DataFrame raises — caller must catch |
| `test_interval_fixed_fallback_on_short_data` | < 20 candles → fixed ±2% |
| `test_interval_fixed_fallback_on_exactly_19_candles` | boundary: 19 → fixed |
| `test_interval_uses_vol_on_20_candles` | boundary: 20 → vol path |
| `test_interval_fallback_marker_in_features` | fallback features dict = `{"interval_fallback": ...}` only |
| `test_ape_zero_for_perfect_prediction` | metrics: APE(100, 100) = 0 |
| `test_ape_handles_zero_actual` | metrics: APE(p, 0) = inf |
| `test_interval_score_perfect` | metrics: exact overlap → score > 0 |
| `test_interval_score_no_overlap` | metrics: disjoint intervals → score = 0 |

### `test_recorder_schema_v2.py` — 4 tests
Phase 1 forecasts.jsonl schema v2 contract.

| Test | Asserts |
|---|---|
| `test_v2_row_with_features` | `schema_version="v2"`, features nested (never flattened) |
| `test_v2_row_without_features_omits_key` | when `features=None`, `features` key is absent (not null) |
| `test_fill_realized_tolerates_mixed_v1_and_v2` | backfill handles both schemas; v1 stays v1, v2 keeps features |
| `test_logged_features_equal_forecast_return_values` | property test: logged dict == `fcst.features \| itvl.features` |

## Conventions

- Every test file uses synthetic `pd.DataFrame` candles generated via `numpy.random.default_rng(seed=...)` for determinism.
- Network-touching code (`fetch_candles`, etc.) is monkeypatched in `test_recorder_schema_v2.py`; no test actually hits Binance.
- `tmp_path` + `monkeypatch.setattr(recorder_mod, "FORECAST_LOG_FILE", ...)` is the pattern for isolating JSONL writes.
