"""
Timestamp utilities consistent with Precog's ISO 8601 / UTC convention.

Precog timestamps look like: "2024-11-14T18:15:00.000000Z"
All timestamps in this project are UTC.
"""
from datetime import datetime, timezone


def now_utc() -> datetime:
    """Return the current UTC datetime (timezone-aware)."""
    return datetime.now(timezone.utc)


def iso_now() -> str:
    """Return the current UTC time as a Precog-style ISO 8601 string."""
    return now_utc().strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def ms_to_utc(ms: int) -> datetime:
    """Convert a Unix millisecond timestamp to a UTC datetime."""
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
