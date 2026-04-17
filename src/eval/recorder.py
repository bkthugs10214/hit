"""
Forecast logger and offline evaluator — SQLite backend.

Storage: ~/.precog_baseline/forecasts.db  (single `forecasts` table)
Schema:  see eval/db.py

log_forecast()  — INSERT one row per prediction (called from forward function)
fill_realized() — UPDATE rows whose 1-hour horizon has elapsed (called from main.py)
"""
import logging
from datetime import datetime, timedelta, timezone

from precog_baseline_miner.config import DB_FILE
from precog_baseline_miner.eval.db import get_conn, init_db
from precog_baseline_miner.eval.metrics import ape as compute_ape
from precog_baseline_miner.eval.metrics import interval_score as compute_interval_score

logger = logging.getLogger(__name__)

# Initialise schema on first import — safe (uses IF NOT EXISTS)
init_db(DB_FILE)


def log_forecast(
    asset: str,
    timestamp: str,
    spot: float,
    point: float,
    low: float,
    high: float,
    binance_snap: dict | None = None,
    cm_snap: dict | None = None,
) -> None:
    """
    INSERT one forecast row into the SQLite `forecasts` table.

    Silently swallows errors so a DB failure never crashes the forward function.
    """
    b = binance_snap or {}
    c = cm_snap or {}
    logged_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"

    try:
        conn = get_conn(DB_FILE)
        conn.execute(
            """
            INSERT INTO forecasts (
                logged_at, prediction_ts, asset, spot, point, low, high,
                b_ret_5m, b_ret_15m, b_ret_60m, b_rvol_1m,
                b_volume_60m, b_vwap_60m, b_n_candles,
                cm_available, cm_spot, cm_ret_1h, cm_rvol_1m,
                cm_n_obs, cm_frequency, cm_source
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                logged_at, timestamp, asset, spot, point, low, high,
                b.get("ret_5m"), b.get("ret_15m"), b.get("ret_60m"),
                b.get("rvol_1m"), b.get("volume_60m"), b.get("vwap_60m"),
                b.get("n_candles"),
                1 if c.get("available") else 0,
                c.get("cm_spot"), c.get("cm_ret_1h"), c.get("cm_rvol_1m"),
                c.get("n_observations"), c.get("frequency"), c.get("source"),
            ),
        )
        conn.commit()
    except Exception as exc:
        logger.error("Failed to write forecast to DB: %s", exc)


def fill_realized() -> int:
    """
    UPDATE rows whose 1-hour evaluation horizon has passed with realized prices.

    Fetches 1-min Binance candles for the prediction window, computes APE and
    interval score, and writes them back.  Returns the number of rows updated.
    """
    # Import here to avoid circular imports (binance_client → config, not eval)
    from precog_baseline_miner.data.binance_client import fetch_candles

    conn = get_conn(DB_FILE)
    rows = conn.execute(
        "SELECT id, asset, prediction_ts, point, low, high "
        "FROM forecasts WHERE realized_price_1h IS NULL"
    ).fetchall()

    if not rows:
        return 0

    now = datetime.now(timezone.utc)
    updated = 0

    for row in rows:
        try:
            pred_ts = datetime.fromisoformat(
                row["prediction_ts"].replace("Z", "+00:00")
            )
        except (KeyError, ValueError) as exc:
            logger.debug("Cannot parse prediction_ts for id=%s: %s", row["id"], exc)
            continue

        eval_ts = pred_ts + timedelta(hours=1)
        if eval_ts > now:
            continue

        try:
            start_ms = int(pred_ts.timestamp() * 1000)
            end_ms   = int(eval_ts.timestamp() * 1000)

            candles = fetch_candles(
                row["asset"],
                interval="1m",
                limit=65,
                start_ms=start_ms,
                end_ms=end_ms,
            )

            if candles.empty:
                logger.warning("No candles returned for %s fill_realized", row["asset"])
                continue

            realized_price = float(candles["close"].iloc[-1])
            realized_min   = float(candles["low"].min())
            realized_max   = float(candles["high"].max())
            ape_val        = compute_ape(row["point"], realized_price)
            is_val         = compute_interval_score(
                row["low"], row["high"], realized_min, realized_max
            )

            conn.execute(
                """
                UPDATE forecasts
                SET realized_price_1h=?, realized_min_1h=?, realized_max_1h=?,
                    ape=?, interval_score=?
                WHERE id=?
                """,
                (realized_price, realized_min, realized_max, ape_val, is_val, row["id"]),
            )
            conn.commit()
            updated += 1

        except Exception as exc:
            logger.warning(
                "Could not fill realized for asset=%s ts=%s: %s",
                row["asset"], row["prediction_ts"], exc,
            )

    if updated:
        logger.info("fill_realized: updated %d record(s)", updated)

    return updated
