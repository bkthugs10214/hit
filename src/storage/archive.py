"""
Layer 2 — Raw Archive (canonical, append-only, never rewritten).

Each event is a zstd-compressed JSON line written as an independent
compressed frame so the file is safely appendable.  Multi-frame reads
are handled transparently by ZstdDecompressor.stream_reader().

On-disk layout:
    {DATA_DIR}/raw/{source}/{channel}/{entity}/{year}/{month}/{day}/{hour}.jsonl.zst

Envelope schema:
    {
      "ingested_at": "2024-11-14T18:15:01.123456Z",
      "source":      "precog",
      "channel":     "forecasts",
      "entity":      "btc",
      "payload":     { ... original data ... }
    }
"""
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

import zstandard as zstd

_CCTX = zstd.ZstdCompressor(level=3)
_DCTX = zstd.ZstdDecompressor()


def _path(
    data_dir: Path,
    source: str,
    channel: str,
    entity: str,
    dt: datetime,
) -> Path:
    return (
        data_dir / "raw" / source / channel / entity
        / f"{dt.year}"
        / f"{dt.month:02d}"
        / f"{dt.day:02d}"
        / f"{dt.hour:02d}.jsonl.zst"
    )


def write_event(
    data_dir: Path,
    source: str,
    channel: str,
    entity: str,
    payload: dict,
    *,
    dt: datetime | None = None,
) -> None:
    """
    Append one event envelope to the appropriate hourly archive file.

    Each call writes a self-contained zstd frame — safe to call concurrently
    from multiple threads (OS-level atomic appends on POSIX, each frame is
    an independent unit).
    """
    now = dt or datetime.now(timezone.utc)
    path = _path(data_dir, source, channel, entity, now)
    path.parent.mkdir(parents=True, exist_ok=True)

    envelope = {
        "ingested_at": now.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z",
        "source": source,
        "channel": channel,
        "entity": entity,
        "payload": payload,
    }
    frame = _CCTX.compress((json.dumps(envelope) + "\n").encode())
    with open(path, "ab") as fh:
        fh.write(frame)


def read_file(path: Path) -> Generator[dict, None, None]:
    """Yield all event envelopes from a single .jsonl.zst file."""
    if not path.exists():
        return
    with open(path, "rb") as fh:
        reader = _DCTX.stream_reader(fh)
        for line in io.TextIOWrapper(reader, encoding="utf-8"):
            line = line.strip()
            if line:
                yield json.loads(line)


def iter_events(
    data_dir: Path,
    source: str,
    channel: str,
    entity: str = "*",
) -> Generator[dict, None, None]:
    """
    Yield all events for source/channel across all entities and time,
    ordered by file path (which sorts chronologically).
    """
    base = data_dir / "raw" / source / channel
    if not base.exists():
        return
    if entity == "*":
        paths = sorted(base.glob("**/*.jsonl.zst"))
    else:
        paths = sorted((base / entity).glob("**/*.jsonl.zst"))
    for path in paths:
        yield from read_file(path)
