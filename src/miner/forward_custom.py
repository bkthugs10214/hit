"""
Precog-compatible forward function — baseline miner.

Deployment
----------
This file is copied to precog/miners/baseline_miner.py by deploy.sh.
The Precog Miner class loads it dynamically via:

    importlib.import_module(f"precog.miners.{config.forward_function}")

and calls it as:

    synapse = await self.forward_module.forward(synapse, self.cm)

So `forward` must be async and accept (synapse, cm).

Protocol contract (precog/protocol.py)
---------------------------------------
  synapse.assets       — List[str] from validator, e.g. ["btc","eth","tao_bittensor"]
  synapse.timestamp    — ISO 8601 UTC string, e.g. "2024-11-14T18:15:00.000000Z"
  synapse.predictions  — Dict[str,float]        ← we set this
  synapse.intervals    — Dict[str,List[float]]  ← we set this  ([min, max])

Fallback chain
--------------
1. Binance public REST API  (primary — no auth required)
2. CoinMetrics cm client    (fallback — needs CM_API_KEY in env)
3. Skip the asset           (better to omit than to return garbage)
"""
import time

import bittensor as bt

from precog_baseline_miner.config import (
    DEFAULT_CANDLE_LIMIT,
    INTERVAL_MULTIPLIER,
    POINT_SHRINKAGE,
)
from precog_baseline_miner.data.binance_client import fetch_candles
from precog_baseline_miner.data.candles import binance_snapshot
from precog_baseline_miner.data.cm_client import cm_snapshot, fetch_reference_rates
from precog_baseline_miner.eval.recorder import log_forecast
from precog_baseline_miner.forecast.baseline import compute_point_forecast
from precog_baseline_miner.forecast.interval import compute_interval
from precog_baseline_miner.miner.adapter import ASSET_SYMBOL_MAP, cm_fallback

# Fixed fallback margin when everything else fails: ±2% around latest price
_HARD_FALLBACK_MARGIN_PCT = 0.02


async def forward(synapse, cm):
    """
    Async forward function called by the Precog Miner for every validator request.

    For each requested asset:
      1. Fetch 100 × 1-min candles from Binance (public API, no key needed)
      2. Compute point forecast  (momentum + shrinkage)
      3. Compute interval        (realized-vol half-width, clamped)
      4. Log the forecast to ~/.precog_baseline/forecasts.jsonl
      5. On Binance failure → try CoinMetrics cm client as fallback
      6. On total failure  → skip the asset (log error, do not crash)
    """
    raw_assets = getattr(synapse, "assets", None) or ["btc"]
    assets = [a.lower() for a in raw_assets]

    bt.logging.info(
        f"[baseline] forward called | assets={assets} | ts={getattr(synapse, 'timestamp', '?')}"
    )

    predictions: dict[str, float] = {}
    intervals: dict[str, list[float]] = {}

    for asset in assets:
        if asset not in ASSET_SYMBOL_MAP:
            bt.logging.warning(f"[baseline] Unknown asset '{asset}' — skipping")
            continue

        # ── Primary path: Binance ─────────────────────────────────────────────
        try:
            _asset_t0 = time.perf_counter()

            candles, b_latency_ms = fetch_candles(asset, limit=DEFAULT_CANDLE_LIMIT)
            spot  = float(candles["close"].iloc[-1])
            point = compute_point_forecast(candles, shrinkage=POINT_SHRINKAGE)
            lo, hi = compute_interval(candles, point, multiplier=INTERVAL_MULTIPLIER)

            b_snap = binance_snapshot(candles)

            # Fetch CoinMetrics reference rates — failures never block the forecast.
            cm_latency_ms: float | None = None
            try:
                cm_df, cm_latency_ms = fetch_reference_rates(asset, frequency="1m", lookback_hours=1)
                c_snap = cm_snapshot(cm_df)
            except Exception as cm_exc:
                bt.logging.debug(f"[baseline] CM data unavailable for '{asset}': {cm_exc}")
                c_snap = {"available": False}

            predictions[asset] = round(point, 4)
            intervals[asset]   = [round(lo, 4), round(hi, 4)]

            forward_ms = round((time.perf_counter() - _asset_t0) * 1000, 1)

            log_forecast(
                asset=asset,
                timestamp=str(getattr(synapse, "timestamp", "")),
                spot=spot,
                point=point,
                low=lo,
                high=hi,
                binance_snap=b_snap,
                cm_snap=c_snap,
                latency_binance_ms=b_latency_ms,
                latency_cm_ms=cm_latency_ms,
                latency_forward_ms=forward_ms,
            )

            bt.logging.info(
                f"[baseline] {asset}: spot=${spot:.2f}  "
                f"point=${point:.2f}  interval=[${lo:.2f}, ${hi:.2f}]  "
                f"latency=binance:{b_latency_ms:.0f}ms"
                + (f" cm:{cm_latency_ms:.0f}ms" if cm_latency_ms is not None else "")
                + f" total:{forward_ms:.0f}ms"
            )
            continue  # success — move to next asset

        except Exception as binance_exc:
            bt.logging.warning(
                f"[baseline] Binance failed for '{asset}': {binance_exc} "
                f"— trying CoinMetrics fallback"
            )

        # ── Fallback path: CoinMetrics cm client ──────────────────────────────
        try:
            spot = cm_fallback(asset, cm)
            margin = spot * _HARD_FALLBACK_MARGIN_PCT
            predictions[asset] = round(spot, 4)
            intervals[asset] = [round(spot - margin, 4), round(spot + margin, 4)]

            bt.logging.info(
                f"[baseline] {asset}: cm fallback spot=${spot:.2f} "
                f"interval=[${spot - margin:.2f}, ${spot + margin:.2f}]"
            )

        except Exception as cm_exc:
            bt.logging.error(
                f"[baseline] Both Binance and CoinMetrics failed for '{asset}': {cm_exc} "
                f"— omitting asset from response"
            )
            # Do NOT add this asset to predictions/intervals — a missing asset
            # is scored as 0 reward, which is better than a nonsense value.

    synapse.predictions = predictions if predictions else None
    synapse.intervals = intervals if intervals else None

    if synapse.predictions:
        bt.logging.success(
            f"[baseline] Done | predictions={list(synapse.predictions.keys())}"
        )
    else:
        bt.logging.warning("[baseline] No predictions produced for this request")

    return synapse
