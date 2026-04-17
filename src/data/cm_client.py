"""
Direct CoinMetrics REST API client.

Works standalone (no Precog CMData dependency) using either:
  - Community API: https://community-api.coinmetrics.io/v4  (free, no key)
  - Paid API:      https://api.coinmetrics.io/v4            (set CM_API_KEY env)

The community tier provides reference rates at 1m frequency with some
rate limiting. For production miners with a CM_API_KEY, 1s frequency
is available and matches what the Precog validator uses for scoring.

Response format from GET /timeseries/asset-metrics:
  {
    "data": [
      {"asset": "btc", "time": "2024-01-15T10:00:00.000000000Z", "ReferenceRateUSD": "42500.0"},
      ...
    ]
  }
"""
import logging
import os
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

logger = logging.getLogger(__name__)

# CoinMetrics asset names (different from Precog/Binance names)
CM_ASSET_MAP: dict[str, str] = {
    "btc":           "btc",
    "eth":           "eth",
    "tao_bittensor": "tao",   # TAO/Bittensor on CoinMetrics
}

_COMMUNITY_BASE = "https://community-api.coinmetrics.io/v4"
_PAID_BASE      = "https://api.coinmetrics.io/v4"
_METRICS_PATH   = "/timeseries/asset-metrics"
_REQUEST_TIMEOUT = 15


def _base_url() -> str:
    return _PAID_BASE if os.environ.get("CM_API_KEY") else _COMMUNITY_BASE


def fetch_reference_rates(
    asset: str,
    frequency: str = "1m",
    lookback_hours: int = 1,
) -> pd.DataFrame:
    """
    Fetch CoinMetrics ReferenceRateUSD for one asset.

    Args:
        asset:          Precog asset name (e.g. "btc", "eth", "tao_bittensor").
                        Mapped to CoinMetrics name via CM_ASSET_MAP.
        frequency:      "1m" for community tier, "1s" requires paid API key.
        lookback_hours: how many hours of history to fetch (default 1).

    Returns:
        DataFrame with columns ["time" (UTC datetime), "ReferenceRateUSD" (float)].
        Empty DataFrame if the asset is not in CM_ASSET_MAP or the API call fails.

    Raises:
        KeyError:           if asset has no CoinMetrics mapping.
        requests.HTTPError: if the API returns a 4xx/5xx status.
    """
    cm_asset = CM_ASSET_MAP.get(asset.lower())
    if not cm_asset:
        raise KeyError(f"No CoinMetrics asset mapping for '{asset}'")

    now   = datetime.now(timezone.utc)
    start = now - timedelta(hours=lookback_hours)

    params: dict = {
        "assets":     cm_asset,
        "metrics":    "ReferenceRateUSD",
        "frequency":  frequency,
        "start_time": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end_time":   now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "page_size":  1000,
    }
    api_key = os.environ.get("CM_API_KEY", "")
    if api_key:
        params["api_key"] = api_key

    url = _base_url() + _METRICS_PATH
    logger.debug("Fetching CM reference rates: asset=%s freq=%s", cm_asset, frequency)

    resp = requests.get(url, params=params, timeout=_REQUEST_TIMEOUT)
    resp.raise_for_status()

    rows = resp.json().get("data", [])
    if not rows:
        logger.warning("CoinMetrics returned 0 rows for asset=%s", cm_asset)
        return _empty_rates_df()

    df = pd.DataFrame(rows)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df["ReferenceRateUSD"] = pd.to_numeric(df["ReferenceRateUSD"], errors="coerce")
    return df[["time", "ReferenceRateUSD"]].dropna().reset_index(drop=True)


def cm_snapshot(df: pd.DataFrame) -> dict:
    """
    Summarise a reference-rate DataFrame into a compact loggable dict.

    Computes:
      cm_spot    — latest reference rate
      cm_ret_1h  — return from first to last observation
      cm_rvol_1m — std of 1-min percentage returns (proxy for CM-side vol)
      n_observations — number of rows in df
      frequency / source — metadata

    Args:
        df: DataFrame from fetch_reference_rates(), columns [time, ReferenceRateUSD].

    Returns:
        Dict with keys: available, cm_spot, cm_ret_1h, cm_rvol_1m,
        n_observations, frequency, source.
        Returns {"available": False} if df is empty.
    """
    if df.empty:
        return {"available": False}

    rates = df["ReferenceRateUSD"].dropna()
    if rates.empty:
        return {"available": False}

    cm_spot   = float(rates.iloc[-1])
    cm_ret_1h = float(rates.iloc[-1] / rates.iloc[0] - 1) if len(rates) >= 2 else None
    cm_rvol   = float(rates.pct_change().dropna().std()) if len(rates) >= 5 else None

    source = "paid" if os.environ.get("CM_API_KEY") else "community"

    return {
        "available":      True,
        "cm_spot":        cm_spot,
        "cm_ret_1h":      cm_ret_1h,
        "cm_rvol_1m":     cm_rvol,
        "n_observations": int(len(rates)),
        "frequency":      "1m",
        "source":         source,
    }


def _empty_rates_df() -> pd.DataFrame:
    return pd.DataFrame(columns=["time", "ReferenceRateUSD"]).astype({
        "time": "datetime64[ns, UTC]",
        "ReferenceRateUSD": "float64",
    })
