"""
Normalize a SentimentBundle into a single [-1, 1] forecast signal.

Three sources, each normalized to [-1, 1]:
  - Fear & Greed (0–100): signal = (value - 50) / 50
  - CryptoPanic: already [-1, 1] (vote-weighted news score)
  - Reddit: weighted upvote-ratio signal, already [-1, 1]

When all three are present, blended 50% F&G / 30% CP / 20% Reddit.
When a subset is present, weights are redistributed proportionally.
Returns None when no valid data is available — callers fall back to
momentum-only forecasting.
"""
import logging

from precog_baseline_miner.data.sentiment import SentimentBundle

logger = logging.getLogger(__name__)

# Relative weights — normalized at runtime based on which sources are available
_BASE_WEIGHTS = {"fg": 0.50, "cp": 0.30, "rd": 0.20}


def sentiment_signal(bundle: SentimentBundle) -> float | None:
    """
    Combine Fear & Greed, CryptoPanic, and Reddit into a single [-1, 1] signal.

    Returns:
        Float in [-1, 1] where negative = bearish, positive = bullish.
        None if no valid source data is available.
    """
    fg_signal: float | None = None
    cp_signal: float | None = None
    rd_signal: float | None = None

    if bundle.fear_greed is not None:
        fg_signal = (bundle.fear_greed.value - 50.0) / 50.0

    if bundle.cryptopanic is not None:
        cp_signal = bundle.cryptopanic.score

    if bundle.reddit is not None:
        rd_signal = bundle.reddit.score

    signals = {
        "fg": fg_signal,
        "cp": cp_signal,
        "rd": rd_signal,
    }
    available = {k: v for k, v in signals.items() if v is not None}

    if not available:
        logger.debug("No sentiment data available — signal is None")
        return None

    total_weight = sum(_BASE_WEIGHTS[k] for k in available)
    combined = sum(_BASE_WEIGHTS[k] * v for k, v in available.items()) / total_weight

    clamped = max(-1.0, min(1.0, combined))
    logger.debug(
        "Sentiment signal: fg=%s  cp=%s  rd=%s  combined=%.4f",
        f"{fg_signal:.3f}" if fg_signal is not None else "N/A",
        f"{cp_signal:.3f}" if cp_signal is not None else "N/A",
        f"{rd_signal:.3f}" if rd_signal is not None else "N/A",
        clamped,
    )
    return clamped
