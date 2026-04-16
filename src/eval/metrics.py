"""
Offline scoring metrics mirroring the Precog reward functions.

These are used in recorder.py to fill in `ape` and `interval_score` after
the 1-hour horizon passes, so you can monitor miner quality locally without
needing to query the validator.

Source: precog/validators/reward.py
"""


def ape(predicted: float, actual: float) -> float:
    """
    Absolute percentage error for a point forecast.

    Lower is better.  A score of 0.01 means the prediction was off by 1%.

    Args:
        predicted: our point forecast
        actual:    realized price at the 1-hour horizon

    Returns:
        |predicted - actual| / actual, or inf if actual is 0.
    """
    if actual == 0:
        return float("inf")
    return abs(predicted - actual) / actual


def interval_score(
    pred_low: float,
    pred_high: float,
    obs_low: float,
    obs_high: float,
) -> float:
    """
    Replicate the Precog interval scoring formula using aggregate min/max.

    NOTE: The live validator uses 1-second prices for inclusion_factor; here
    we use the aggregate [obs_low, obs_high] as an approximation, which makes
    this a lower-bound estimate of the true interval score.

    Higher is better.  Score ∈ [0, 1].

    Args:
        pred_low, pred_high: our predicted interval bounds
        obs_low, obs_high:   actual min/max prices over the horizon

    Returns:
        inclusion_factor × width_factor (approximate)
    """
    pred_width = pred_high - pred_low
    if pred_width <= 0:
        return 0.0

    # Overlap between predicted and observed ranges
    effective_top = min(pred_high, obs_high)
    effective_bottom = max(pred_low, obs_low)
    overlap = max(0.0, effective_top - effective_bottom)

    # width_factor: how much of our predicted range overlaps the observed range
    width_factor = overlap / pred_width

    # inclusion_factor (approximate): fraction of the observed range we covered
    obs_width = obs_high - obs_low
    if obs_width <= 0:
        # Price was flat — did we contain it?
        inclusion_factor = 1.0 if pred_low <= obs_low <= pred_high else 0.0
    else:
        inclusion_factor = min(overlap / obs_width, 1.0)

    return inclusion_factor * width_factor
