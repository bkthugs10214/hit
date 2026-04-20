"""
Normalize a SentimentBundle into a single [-1, 1] forecast signal.

Fear & Greed (0–100) is rescaled with 50 as neutral:
    signal = (value - 50) / 50

CryptoPanic score is already in [-1, 1].

When both sources are present they are blended 60% F&G / 40% CryptoPanic.
When only one is present it is used directly.
Returns None when no valid data is available — callers fall back to
momentum-only forecasting.
"""
import logging

from precog_baseline_miner.data.sentiment import SentimentBundle

logger = logging.getLogger(__name__)

_FG_WEIGHT = 0.6
_CP_WEIGHT = 0.4


def sentiment_signal(bundle: SentimentBundle) -> float | None:
    """
    Combine Fear & Greed and CryptoPanic into a single [-1, 1] signal.

    Returns:
        Float in [-1, 1] where negative = bearish, positive = bullish.
        None if no valid source data is available.
    """
    fg_signal: float | None = None
    cp_signal: float | None = None

    if bundle.fear_greed is not None:
        fg_signal = (bundle.fear_greed.value - 50.0) / 50.0

    if bundle.cryptopanic is not None:
        cp_signal = bundle.cryptopanic.score

    if fg_signal is not None and cp_signal is not None:
        combined = _FG_WEIGHT * fg_signal + _CP_WEIGHT * cp_signal
    elif fg_signal is not None:
        combined = fg_signal
    elif cp_signal is not None:
        combined = cp_signal
    else:
        logger.debug("No sentiment data available — signal is None")
        return None

    clamped = max(-1.0, min(1.0, combined))
    logger.debug(
        "Sentiment signal: fg=%s  cp=%s  combined=%.4f",
        f"{fg_signal:.3f}" if fg_signal is not None else "N/A",
        f"{cp_signal:.3f}" if cp_signal is not None else "N/A",
        clamped,
    )
    return clamped
