"""
Normalize a FuturesBundle into a single [-1, 1] forecast signal.

Funding rate interpretation (contrarian at 1-hour horizon):
  - Positive funding: longs pay shorts → longs are crowded → mean-revert bearish
  - Negative funding: shorts pay longs → shorts are crowded → mean-revert bullish
  - Signal is therefore INVERTED: high positive funding → negative (bearish) signal

Normalization reference: 0.001 (0.1% per cycle). This is a moderate-extreme
level for BTC/ETH. The signal is clamped to [-1, 1], so larger rates (e.g. TAO
at ±3% max) are still handled correctly via clamping.

Returns None when no valid futures data is available.
"""
import logging

from precog_baseline_miner.data.futures import FuturesBundle

logger = logging.getLogger(__name__)

# Funding rate at which the signal saturates to ±1.
# 0.001 = 0.1% per settlement cycle — moderate-extreme for BTC/ETH.
_FUNDING_REFERENCE = 0.001


def futures_signal(bundle: FuturesBundle) -> float | None:
    """
    Derive a [-1, 1] directional signal from futures metrics.

    Currently uses funding rate only (contrarian). Open interest is recorded
    but not yet used as a feature — needs baseline history first.

    Returns:
        Float in [-1, 1]: negative = bearish pressure, positive = bullish.
        None if no valid futures data.
    """
    if bundle.mexc is None:
        logger.debug("No futures data available — signal is None")
        return None

    raw = bundle.mexc.funding_rate
    # Invert: high positive funding → bears will follow → negative signal
    normalized = -(raw / _FUNDING_REFERENCE)
    clamped = max(-1.0, min(1.0, normalized))

    logger.debug(
        "Futures signal: funding=%+.6f  normalized=%+.4f  clamped=%+.4f",
        raw, normalized, clamped,
    )
    return clamped
