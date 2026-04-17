"""
SQLite database setup and connection management.

Single table design: `forecasts` is a wide, denormalised table that stores
forecast outputs, Binance input snapshot, CoinMetrics input snapshot, and
realized outcomes in one row per asset per prediction.

This makes common analytical queries simple — no JOINs needed:

    SELECT asset, AVG(ape) FROM forecasts WHERE ape IS NOT NULL GROUP BY asset;
    SELECT * FROM forecasts WHERE b_ret_5m > 0.002 AND asset = 'btc';
    SELECT cm_spot - spot AS cm_basis FROM forecasts WHERE cm_available = 1;

Schema
------
See _SCHEMA below for the full column list.

Threading
---------
SQLite in WAL mode supports concurrent readers and one writer at a time.
We use a module-level lock for writes and thread-local connections for reads
so the forward function can safely call log_forecast from multiple threads.
"""
import sqlite3
import threading
from pathlib import Path

_local = threading.local()
_write_lock = threading.Lock()

# ── Schema ────────────────────────────────────────────────────────────────────
_SCHEMA = """
CREATE TABLE IF NOT EXISTS forecasts (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,

    -- When and what
    logged_at         TEXT    NOT NULL,   -- wall-clock UTC ISO 8601
    prediction_ts     TEXT    NOT NULL,   -- validator request timestamp
    asset             TEXT    NOT NULL,   -- "btc" | "eth" | "tao_bittensor"

    -- Forecast outputs
    spot              REAL,               -- price at prediction time (Binance)
    point             REAL,               -- point forecast
    low               REAL,               -- interval lower bound
    high              REAL,               -- interval upper bound

    -- Binance input snapshot (from 100 x 1-min OHLCV candles)
    b_ret_5m          REAL,               -- 5-min momentum return
    b_ret_15m         REAL,               -- 15-min momentum return
    b_ret_60m         REAL,               -- 60-min momentum return
    b_rvol_1m         REAL,               -- std of 1-min pct returns
    b_volume_60m      REAL,               -- total volume, last 60 candles
    b_vwap_60m        REAL,               -- VWAP, last 60 candles
    b_n_candles       INTEGER,            -- candles available

    -- CoinMetrics input snapshot (from reference rate series)
    cm_available      INTEGER,            -- 1 = fetched OK, 0 = unavailable
    cm_spot           REAL,               -- latest CM reference rate
    cm_ret_1h         REAL,               -- 1-hour return (first→last obs)
    cm_rvol_1m        REAL,               -- std of 1-min pct returns (CM)
    cm_n_obs          INTEGER,            -- number of CM observations
    cm_frequency      TEXT,               -- "1m" or "1s"
    cm_source         TEXT,               -- "community" or "paid"

    -- Realized outcomes (back-filled ~1 hour after prediction)
    realized_price_1h REAL,
    realized_min_1h   REAL,
    realized_max_1h   REAL,
    ape               REAL,               -- |point - realized| / realized
    interval_score    REAL                -- inclusion × width (approx)
);

CREATE INDEX IF NOT EXISTS idx_asset_ts
    ON forecasts (asset, prediction_ts);

CREATE INDEX IF NOT EXISTS idx_unfilled
    ON forecasts (prediction_ts)
    WHERE realized_price_1h IS NULL;
"""


# ── Connection management ─────────────────────────────────────────────────────

def _connect(db_file: Path) -> sqlite3.Connection:
    """Open a new SQLite connection with recommended pragmas."""
    conn = sqlite3.connect(str(db_file), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")      # concurrent reads during writes
    conn.execute("PRAGMA synchronous=NORMAL")    # safe + fast
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_conn(db_file: Path) -> sqlite3.Connection:
    """
    Return a thread-local SQLite connection, creating it on first access.

    Args:
        db_file: Path to the SQLite database file (from config.DB_FILE).
    """
    key = str(db_file)
    if getattr(_local, "conn_key", None) != key or _local.__dict__.get("conn") is None:
        _local.conn = _connect(db_file)
        _local.conn_key = key
    return _local.conn


# ── Schema initialisation ─────────────────────────────────────────────────────

def init_db(db_file: Path) -> None:
    """
    Create the `forecasts` table and indexes if they do not already exist.

    Safe to call on every startup — uses CREATE TABLE IF NOT EXISTS.
    """
    with _write_lock:
        conn = get_conn(db_file)
        conn.executescript(_SCHEMA)
        conn.commit()
