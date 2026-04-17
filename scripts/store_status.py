#!/usr/bin/env python3
"""
store_status.py — Summarize the state of the precog miner local data store.

Usage:
    python scripts/store_status.py [OPTIONS]

Options:
    -d, --data-dir PATH    Root data directory
                           (default: $PRECOG_BASELINE_DATA_DIR or ~/.precog_baseline)
    -a, --asset SYMBOL     Filter all output to one asset, e.g. btc
    -l, --layer LAYER      Show only one layer: raw | normalized | serving
    -j, --json             Machine-readable JSON output
    -v, --verbose          Show per-file detail and decompress archives for event counts
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Allow running directly from the project root without installing the package.
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from precog_baseline_miner.config import DATA_DIR as _DEFAULT_DATA_DIR

# ── Helpers ───────────────────────────────────────────────────────────────────

_COL_W = 62  # banner width


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def _fmt_int(n: int) -> str:
    return f"{n:,}"


def _dir_stats(path: Path) -> tuple[int, int]:
    """Return (file_count, total_bytes) for a directory tree."""
    if not path.exists():
        return 0, 0
    count = total = 0
    for root, _, files in os.walk(path):
        for fname in files:
            try:
                total += os.stat(os.path.join(root, fname)).st_size
                count += 1
            except OSError:
                pass
    return count, total


def _parse_date_from_archive_path(p: Path, entity_dir: Path) -> str | None:
    """Extract YYYY-MM-DD from paths like entity/YYYY/MM/DD/HH.jsonl.zst."""
    try:
        parts = p.relative_to(entity_dir).parts  # (year, month, day, HH.jsonl.zst)
        return f"{parts[0]}-{parts[1]}-{parts[2]}"
    except Exception:
        return None


# ── Data collectors ───────────────────────────────────────────────────────────

def _collect_disk(data_dir: Path) -> dict[str, Any]:
    layers = ["raw", "normalized", "features", "serving"]
    result: dict[str, Any] = {}
    total_files = total_bytes = 0
    for layer in layers:
        fc, fb = _dir_stats(data_dir / layer)
        result[layer] = {"files": fc, "bytes": fb}
        total_files += fc
        total_bytes += fb
    result["total"] = {"files": total_files, "bytes": total_bytes}
    return result


def _collect_raw(data_dir: Path, asset_filter: str | None, verbose: bool) -> list[dict]:
    """
    Return one row per (channel, asset).  File count and date range are derived
    from directory path components (no decompression).  Event counts require
    decompression and are only computed with --verbose.
    """
    raw_base = data_dir / "raw" / "precog"
    if not raw_base.exists():
        return []

    rows: list[dict] = []

    for channel_dir in sorted(raw_base.iterdir()):
        if not channel_dir.is_dir():
            continue
        channel = channel_dir.name

        for entity_dir in sorted(channel_dir.iterdir()):
            if not entity_dir.is_dir():
                continue
            asset = entity_dir.name
            if asset_filter and asset != asset_filter:
                continue

            files = sorted(entity_dir.glob("**/*.jsonl.zst"))
            if not files:
                continue

            dates = sorted(filter(None, (_parse_date_from_archive_path(f, entity_dir) for f in files)))
            oldest = dates[0] if dates else "—"
            newest = dates[-1] if dates else "—"

            event_count: int | None = None
            if verbose:
                from precog_baseline_miner.storage import archive
                event_count = sum(
                    1 for _ in archive.iter_events(data_dir, "precog", channel, asset)
                )

            rows.append({
                "channel":      channel,
                "asset":        asset,
                "files":        len(files),
                "oldest":       oldest,
                "newest":       newest,
                "event_count":  event_count,
            })

    return rows


def _collect_normalized(data_dir: Path, asset_filter: str | None) -> list[dict]:
    from precog_baseline_miner.storage.normalize import read_normalized

    rows: list[dict] = []
    for dataset in ("forecasts", "realizations"):
        base = data_dir / "normalized" / dataset
        partitions = len(list(base.glob("date=*"))) if base.exists() else 0

        df = read_normalized(data_dir, dataset)
        if asset_filter and not df.empty:
            df = df[df["asset"] == asset_filter]

        if df.empty:
            rows.append({
                "dataset":    dataset,
                "rows":       0,
                "partitions": partitions,
                "assets":     0,
                "oldest":     "—",
                "newest":     "—",
            })
        else:
            rows.append({
                "dataset":    dataset,
                "rows":       len(df),
                "partitions": partitions,
                "assets":     int(df["asset"].nunique()),
                "oldest":     str(df["prediction_ts"].min())[:10],
                "newest":     str(df["prediction_ts"].max())[:10],
            })
    return rows


def _collect_pending(data_dir: Path, asset_filter: str | None) -> int:
    """Count forecasts whose 1-h horizon has elapsed but lack a realization."""
    import pandas as pd
    from precog_baseline_miner.storage.normalize import read_normalized

    fc = read_normalized(data_dir, "forecasts")
    if fc.empty:
        return 0
    if asset_filter:
        fc = fc[fc["asset"] == asset_filter]
    if fc.empty:
        return 0

    now_ts = datetime.now(timezone.utc)
    fc = fc.copy()
    fc["_eval"] = pd.to_datetime(fc["prediction_ts"], utc=True) + pd.Timedelta("1h")
    eligible = fc[fc["_eval"] < now_ts][["asset", "prediction_ts"]].copy()
    eligible["prediction_ts"] = eligible["prediction_ts"].astype(str)

    rc = read_normalized(data_dir, "realizations")
    if rc.empty:
        return len(eligible)

    rc_keys = rc[["asset", "prediction_ts"]].copy()
    rc_keys["prediction_ts"] = rc_keys["prediction_ts"].astype(str)
    rc_keys = rc_keys.drop_duplicates()
    rc_keys["_realized"] = True

    merged = eligible.merge(rc_keys, on=["asset", "prediction_ts"], how="left")
    return int(merged["_realized"].isna().sum())


def _collect_serving(data_dir: Path, asset_filter: str | None) -> list[dict]:
    import pandas as pd

    ts_base = data_dir / "serving" / "timeseries" / "price_predictions"
    if not ts_base.exists():
        return []

    rows: list[dict] = []
    for gran_dir in sorted(ts_base.iterdir()):
        if not gran_dir.is_dir():
            continue
        granularity = gran_dir.name.replace("granularity=", "")
        parts = sorted(gran_dir.glob("date=*/part-*.parquet"))
        if not parts:
            continue

        frames = [pd.read_parquet(p) for p in parts]
        df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        if asset_filter and not df.empty:
            df = df[df["asset"] == asset_filter]

        def _mean(col: str) -> str:
            if col in df.columns and not df.empty:
                v = df[col].dropna()
                return f"{v.mean():.4f}" if len(v) else "—"
            return "—"

        rows.append({
            "dataset":              "price_predictions",
            "granularity":          granularity,
            "partitions":           len(parts),
            "rows":                 len(df),
            "mean_ape":             _mean("ape"),
            "mean_interval_score":  _mean("interval_score"),
        })
    return rows


# ── Text printers ─────────────────────────────────────────────────────────────

def _rule(char: str = "═") -> str:
    return char * _COL_W


def _banner(data_dir: Path) -> None:
    label = f"  PRECOG DATA STORE  —  {data_dir}  "
    pad_l = (_COL_W - len(label)) // 2
    pad_r = _COL_W - len(label) - pad_l
    print(_rule())
    print("═" * pad_l + label + "═" * pad_r)
    print(_rule())
    print()


def _print_disk(disk: dict) -> None:
    print("DISK USAGE")
    print(f"  {'Layer':<14}  {'Files':>6}   {'Size':>9}")
    any_data = False
    for layer in ("raw", "normalized", "features", "serving"):
        d = disk[layer]
        if d["files"] == 0:
            continue
        print(f"  {layer:<14}  {_fmt_int(d['files']):>6}   {_fmt_bytes(d['bytes']):>9}")
        any_data = True
    if not any_data:
        print("  (empty)")
        return
    t = disk["total"]
    print(f"  {'─' * 34}")
    print(f"  {'TOTAL':<14}  {_fmt_int(t['files']):>6}   {_fmt_bytes(t['bytes']):>9}")
    print()


def _print_raw(rows: list[dict]) -> None:
    title = "RAW ARCHIVE  (Layer 2)"
    if not rows:
        print(f"{title}  — no data\n")
        return

    show_events = any(r["event_count"] is not None for r in rows)
    print(title)
    hdr = f"  {'Channel':<14}  {'Asset':<8}  {'Date Range':<25}  {'Files':>6}"
    if show_events:
        hdr += f"  {'Events':>9}"
    print(hdr)

    for r in rows:
        dr = f"{r['oldest']} → {r['newest']}" if r["oldest"] != "—" else "—"
        line = f"  {r['channel']:<14}  {r['asset']:<8}  {dr:<25}  {_fmt_int(r['files']):>6}"
        if show_events:
            ec = r["event_count"]
            line += f"  {_fmt_int(ec) if ec is not None else '—':>9}"
        print(line)
    print()


def _print_normalized(rows: list[dict], pending: int) -> None:
    title = "NORMALIZED  (Layer 3)"
    if not rows or all(r["rows"] == 0 for r in rows):
        print(f"{title}  — no data\n")
        return

    print(title)
    print(f"  {'Dataset':<16}  {'Rows':>7}  {'Parts':>6}  {'Assets':>6}  {'Oldest':<12}  {'Newest':<12}")
    for r in rows:
        if r["rows"] == 0:
            continue
        print(
            f"  {r['dataset']:<16}  {_fmt_int(r['rows']):>7}  {r['partitions']:>6}"
            f"  {r['assets']:>6}  {r['oldest']:<12}  {r['newest']:<12}"
        )

    label = "Pending realizations (horizon elapsed, not yet filled)"
    print(f"\n  {label}: {_fmt_int(pending)}")
    print()


def _print_serving(rows: list[dict]) -> None:
    title = "SERVING  (Layer 5)"
    if not rows:
        print(f"{title}  — no data\n")
        return

    print(title)
    print(
        f"  {'Dataset':<22}  {'Gran':<6}  {'Parts':>6}  {'Rows':>7}"
        f"  {'Mean APE':>10}  {'Mean IS':>10}"
    )
    for r in rows:
        print(
            f"  {r['dataset']:<22}  {r['granularity']:<6}  {r['partitions']:>6}"
            f"  {_fmt_int(r['rows']):>7}  {r['mean_ape']:>10}  {r['mean_interval_score']:>10}"
        )
    print()


# ── Top-level build / print ───────────────────────────────────────────────────

def build_report(
    data_dir: Path,
    asset_filter: str | None = None,
    layer_filter: str | None = None,
    verbose: bool = False,
) -> dict[str, Any]:
    show = layer_filter or "all"
    report: dict[str, Any] = {"data_dir": str(data_dir)}

    report["disk"] = _collect_disk(data_dir)

    if show in ("all", "raw"):
        report["raw"] = _collect_raw(data_dir, asset_filter, verbose)

    if show in ("all", "normalized"):
        report["normalized"] = _collect_normalized(data_dir, asset_filter)
        report["pending"]    = _collect_pending(data_dir, asset_filter)

    if show in ("all", "serving"):
        report["serving"] = _collect_serving(data_dir, asset_filter)

    return report


def print_report(report: dict[str, Any]) -> None:
    _banner(Path(report["data_dir"]))

    if "disk" in report:
        _print_disk(report["disk"])

    if "raw" in report:
        _print_raw(report["raw"])

    if "normalized" in report:
        _print_normalized(report["normalized"], report.get("pending", 0))

    if "serving" in report:
        _print_serving(report["serving"])

    print(_rule())
    print()


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="store_status",
        description="Summarize the precog miner data store.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-d", "--data-dir",
        default=str(_DEFAULT_DATA_DIR),
        metavar="PATH",
        help="Root data directory (default: %(default)s)",
    )
    parser.add_argument(
        "-a", "--asset",
        default=None,
        metavar="SYMBOL",
        help="Filter to one asset, e.g. btc or eth",
    )
    parser.add_argument(
        "-l", "--layer",
        choices=["raw", "normalized", "serving"],
        default=None,
        metavar="LAYER",
        help="Show only: raw | normalized | serving",
    )
    parser.add_argument(
        "-j", "--json",
        action="store_true",
        help="Emit JSON instead of formatted text",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Decompress archive files to report event counts (slower)",
    )

    args = parser.parse_args()
    data_dir = Path(args.data_dir).expanduser().resolve()

    if not data_dir.exists():
        if args.json:
            print(json.dumps({"data_dir": str(data_dir), "error": "directory not found"}))
        else:
            print(f"No data found at {data_dir}")
        sys.exit(0)

    asset = args.asset.lower() if args.asset else None

    report = build_report(
        data_dir=data_dir,
        asset_filter=asset,
        layer_filter=args.layer,
        verbose=args.verbose,
    )

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print_report(report)


if __name__ == "__main__":
    main()
