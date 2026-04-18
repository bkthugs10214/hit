"""
Layer 3 — Normalization.

Reads raw archive events and writes structured Parquet datasets,
partitioned by date.  Processing is idempotent — safe to re-run.
Today's partition is always rebuilt to pick up new events.

On-disk layout:
    {DATA_DIR}/normalized/{dataset}/date={YYYY-MM-DD}/part-0.parquet
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from precog_baseline_miner.storage import archive

logger = logging.getLogger(__name__)

# Columns written for each normalized dataset
_FORECAST_COLS = [
    "ingested_at", "prediction_ts", "asset",
    "spot", "point", "low", "high",
    "b_ret_5m", "b_ret_15m", "b_ret_60m",
    "b_rvol_1m", "b_volume_60m", "b_vwap_60m", "b_n_candles",
    "cm_available", "cm_spot", "cm_ret_1h", "cm_rvol_1m",
    "cm_n_obs", "cm_frequency", "cm_source",
    "latency_binance_ms", "latency_cm_ms", "latency_forward_ms",
]

_REALIZATION_COLS = [
    "ingested_at", "prediction_ts", "asset",
    "realized_price_1h", "realized_min_1h", "realized_max_1h",
    "ape", "interval_score",
    "latency_binance_ms",
]


def _out_path(data_dir: Path, dataset: str, partition_date: str) -> Path:
    return data_dir / "normalized" / dataset / f"date={partition_date}" / "part-0.parquet"


def _already_normalized(data_dir: Path, dataset: str, partition_date: str) -> bool:
    """Skip dates that have been fully normalized (not today)."""
    today = date.today().isoformat()
    if partition_date == today:
        return False
    return _out_path(data_dir, dataset, partition_date).exists()


def _write_partition(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False, engine="pyarrow")


def normalize_forecasts(data_dir: Path) -> int:
    """
    Rebuild normalized/forecasts Parquet from raw archive.
    Returns the number of partitions written.
    """
    rows: list[dict] = []
    for event in archive.iter_events(data_dir, "precog", "forecasts"):
        p = event["payload"]
        rows.append({
            "ingested_at":   event["ingested_at"],
            "prediction_ts": p.get("prediction_ts"),
            "asset":         p.get("asset"),
            "spot":          p.get("spot"),
            "point":         p.get("point"),
            "low":           p.get("low"),
            "high":          p.get("high"),
            "b_ret_5m":      p.get("b_ret_5m"),
            "b_ret_15m":     p.get("b_ret_15m"),
            "b_ret_60m":     p.get("b_ret_60m"),
            "b_rvol_1m":     p.get("b_rvol_1m"),
            "b_volume_60m":  p.get("b_volume_60m"),
            "b_vwap_60m":    p.get("b_vwap_60m"),
            "b_n_candles":   p.get("b_n_candles"),
            "cm_available":  p.get("cm_available"),
            "cm_spot":       p.get("cm_spot"),
            "cm_ret_1h":     p.get("cm_ret_1h"),
            "cm_rvol_1m":    p.get("cm_rvol_1m"),
            "cm_n_obs":      p.get("cm_n_obs"),
            "cm_frequency":  p.get("cm_frequency"),
            "cm_source":     p.get("cm_source"),
            "latency_binance_ms":  p.get("latency_binance_ms"),
            "latency_cm_ms":       p.get("latency_cm_ms"),
            "latency_forward_ms":  p.get("latency_forward_ms"),
        })

    if not rows:
        return 0

    df = pd.DataFrame(rows)[_FORECAST_COLS]
    df["_date"] = pd.to_datetime(df["prediction_ts"], utc=True).dt.date.astype(str)

    written = 0
    for partition_date, group in df.groupby("_date"):
        if _already_normalized(data_dir, "forecasts", partition_date):
            continue
        _write_partition(group.drop(columns=["_date"]), _out_path(data_dir, "forecasts", partition_date))
        written += 1

    if written:
        logger.info("normalize_forecasts: wrote %d partition(s)", written)
    return written


def normalize_realizations(data_dir: Path) -> int:
    """
    Rebuild normalized/realizations Parquet from raw archive.
    Returns the number of partitions written.
    """
    rows: list[dict] = []
    for event in archive.iter_events(data_dir, "precog", "realizations"):
        p = event["payload"]
        rows.append({
            "ingested_at":        event["ingested_at"],
            "prediction_ts":      p.get("prediction_ts"),
            "asset":              p.get("asset"),
            "realized_price_1h":  p.get("realized_price_1h"),
            "realized_min_1h":    p.get("realized_min_1h"),
            "realized_max_1h":    p.get("realized_max_1h"),
            "ape":                p.get("ape"),
            "interval_score":     p.get("interval_score"),
            "latency_binance_ms": p.get("latency_binance_ms"),
        })

    if not rows:
        return 0

    df = pd.DataFrame(rows)[_REALIZATION_COLS]
    df["_date"] = pd.to_datetime(df["prediction_ts"], utc=True).dt.date.astype(str)

    written = 0
    for partition_date, group in df.groupby("_date"):
        if _already_normalized(data_dir, "realizations", partition_date):
            continue
        _write_partition(group.drop(columns=["_date"]), _out_path(data_dir, "realizations", partition_date))
        written += 1

    if written:
        logger.info("normalize_realizations: wrote %d partition(s)", written)
    return written


def read_normalized(data_dir: Path, dataset: str) -> pd.DataFrame:
    """Read all partitions of a normalized dataset into one DataFrame."""
    base = data_dir / "normalized" / dataset
    if not base.exists():
        return pd.DataFrame()
    parts = sorted(base.glob("date=*/part-*.parquet"))
    if not parts:
        return pd.DataFrame()
    return pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)
