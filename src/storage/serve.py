"""
Layer 5 — Serving (visualization-ready time-series datasets).

Reads normalized forecasts + realizations, merges them, and writes
pre-aggregated Parquet files optimized for charts and dashboards.

On-disk layout:
    {DATA_DIR}/serving/timeseries/{dataset}/granularity={g}/date={YYYY-MM-DD}/part-0.parquet
    {DATA_DIR}/serving/dimensions/entities.parquet
    {DATA_DIR}/serving/dimensions/metrics.parquet
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import pandas as pd

from precog_baseline_miner.storage.normalize import read_normalized

logger = logging.getLogger(__name__)

# Columns exposed to the dashboard layer (stable, minimal schema)
_SERVING_COLS = [
    "prediction_ts", "asset",
    "spot", "point", "low", "high",
    "b_ret_5m", "b_ret_15m", "b_rvol_1m",
    "cm_spot",
    "realized_price_1h", "realized_min_1h", "realized_max_1h",
    "ape", "interval_score",
]


def _serving_path(data_dir: Path, dataset: str, granularity: str, partition_date: str) -> Path:
    return (
        data_dir / "serving" / "timeseries" / dataset
        / f"granularity={granularity}"
        / f"date={partition_date}"
        / "part-0.parquet"
    )


def build_price_predictions(data_dir: Path) -> int:
    """
    Merge normalized forecasts + realizations and write to the serving layer.

    Produces one Parquet file per (date, granularity).  Returns number of
    partitions written.
    """
    forecasts = read_normalized(data_dir, "forecasts")
    if forecasts.empty:
        return 0

    realizations = read_normalized(data_dir, "realizations")

    if not realizations.empty:
        # Deduplicate realizations — keep most-recently ingested per (asset, prediction_ts)
        realizations = (
            realizations
            .sort_values("ingested_at")
            .drop_duplicates(subset=["asset", "prediction_ts"], keep="last")
        )
        outcome_cols = [
            "asset", "prediction_ts",
            "realized_price_1h", "realized_min_1h", "realized_max_1h",
            "ape", "interval_score",
        ]
        df = forecasts.merge(realizations[outcome_cols], on=["asset", "prediction_ts"], how="left")
    else:
        df = forecasts.copy()
        for col in ["realized_price_1h", "realized_min_1h", "realized_max_1h", "ape", "interval_score"]:
            df[col] = None

    # Keep only stable serving columns that exist in the dataframe
    cols = [c for c in _SERVING_COLS if c in df.columns]
    df = df[cols].copy()

    df["_date"] = pd.to_datetime(df["prediction_ts"], utc=True).dt.date.astype(str)

    written = 0
    today = date.today().isoformat()

    for partition_date, group in df.groupby("_date"):
        path = _serving_path(data_dir, "price_predictions", "5m", partition_date)
        # Always rebuild today's partition; skip older ones if they exist
        if partition_date != today and path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        group.drop(columns=["_date"]).to_parquet(path, index=False, engine="pyarrow")
        written += 1

    if written:
        logger.info("build_price_predictions: wrote %d partition(s)", written)
    return written


def build_dimensions(data_dir: Path) -> None:
    """Write dimension tables: entities and metrics."""
    import yaml
    config_dir = Path(__file__).parent.parent.parent / "config"
    dim_dir = data_dir / "serving" / "dimensions"
    dim_dir.mkdir(parents=True, exist_ok=True)

    metrics_file = config_dir / "metrics.yaml"
    datasets_file = config_dir / "datasets.yaml"

    if metrics_file.exists():
        with open(metrics_file) as fh:
            data = yaml.safe_load(fh)
        pd.DataFrame(data.get("metrics", [])).to_parquet(
            dim_dir / "metrics.parquet", index=False, engine="pyarrow"
        )

    if datasets_file.exists():
        with open(datasets_file) as fh:
            data = yaml.safe_load(fh)
        entities = [
            {"dataset": d["name"], "layer": d["layer"], "entity_key": d.get("entity_key", "")}
            for d in data.get("datasets", [])
        ]
        pd.DataFrame(entities).to_parquet(
            dim_dir / "entities.parquet", index=False, engine="pyarrow"
        )


def run_pipeline(data_dir: Path) -> dict[str, int]:
    """
    Run the full normalization + serving pipeline.

    Returns counts of partitions written per step.
    """
    from precog_baseline_miner.storage.normalize import (
        normalize_forecasts,
        normalize_realizations,
    )

    results = {
        "forecasts_normalized": normalize_forecasts(data_dir),
        "realizations_normalized": normalize_realizations(data_dir),
        "serving_partitions": build_price_predictions(data_dir),
    }
    try:
        build_dimensions(data_dir)
    except Exception as exc:
        logger.debug("build_dimensions skipped: %s", exc)

    return results
