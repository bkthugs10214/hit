"""
Reddit community sentiment fetcher — public JSON API.

No authentication required. Uses the public .json endpoint with a descriptive
User-Agent. Subreddit hot posts are scored by weighted upvote ratio:

    signal = Σ( log1p(score) × (upvote_ratio - 0.5) × 2 ) / Σ( log1p(score) )

This maps perfectly-upvoted posts → +1, perfectly-downvoted → -1, and
50/50-split posts → 0. Log-weighting prevents a single viral post from
dominating while still rewarding high-karma signal.

Endpoint: https://www.reddit.com/r/{subreddit}/hot.json?limit=25
"""
import logging
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import requests

from precog_baseline_miner.config import SENTIMENT_CACHE_TTL, SENTIMENT_REQUEST_TIMEOUT, VERBOSE

logger = logging.getLogger(__name__)

_REDDIT_URL = "https://www.reddit.com/r/{subreddit}/hot.json"
_POST_LIMIT = 25
_USER_AGENT = "precog-baseline-miner/1.0 (bittensor subnet 50 research bot)"

_ASSET_SUBREDDIT_MAP: dict[str, str] = {
    "btc":           "Bitcoin",
    "eth":           "ethereum",
    "tao_bittensor": "bittensor_",
}


@dataclass
class RedditResult:
    subreddit: str
    score: float        # weighted upvote-ratio signal in [-1, 1]
    post_count: int     # number of posts used in the calculation
    fetched_at: datetime
    from_cache: bool


# Per-asset TTL cache: asset → (result, expiry_monotonic)
_cache: dict[str, tuple[RedditResult, float]] = {}


def fetch_reddit_sentiment(asset: str, cache_ttl: int = SENTIMENT_CACHE_TTL) -> RedditResult | None:
    """
    Fetch Reddit community sentiment for the given asset.

    Returns a cached result if within TTL. Returns None if the asset has no
    subreddit mapping or on any HTTP/parse failure.

    Args:
        asset:     Precog asset name (e.g. "btc", "eth", "tao_bittensor").
        cache_ttl: seconds to cache the result before re-fetching.
    """
    subreddit = _ASSET_SUBREDDIT_MAP.get(asset.lower())
    if subreddit is None:
        logger.warning("Reddit sentiment: no subreddit mapping for asset '%s'", asset)
        return None

    now_mono = time.monotonic()
    if asset in _cache:
        cached_result, expiry = _cache[asset]
        if now_mono < expiry:
            if VERBOSE:
                logger.debug(
                    "Reddit cache hit for r/%s: score=%.4f  posts=%d",
                    subreddit, cached_result.score, cached_result.post_count,
                )
            return RedditResult(
                subreddit=cached_result.subreddit,
                score=cached_result.score,
                post_count=cached_result.post_count,
                fetched_at=cached_result.fetched_at,
                from_cache=True,
            )

    logger.debug("Fetching Reddit hot posts for r/%s", subreddit)
    try:
        resp = requests.get(
            _REDDIT_URL.format(subreddit=subreddit),
            params={"limit": _POST_LIMIT},
            headers={"User-Agent": _USER_AGENT},
            timeout=SENTIMENT_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        raw = resp.json()

        if VERBOSE:
            logger.debug("Reddit raw payload for r/%s: %d posts", subreddit, len(raw.get("data", {}).get("children", [])))

        posts = raw.get("data", {}).get("children", [])
        if not posts:
            logger.warning("Reddit: no posts returned for r/%s", subreddit)
            return None

        weight_sum = 0.0
        signal_sum = 0.0
        for post in posts:
            pd = post.get("data", {})
            karma = pd.get("score", 0)
            ratio = pd.get("upvote_ratio", 0.5)
            w = math.log1p(max(0, karma))
            weight_sum += w
            signal_sum += w * (ratio - 0.5) * 2.0

            if VERBOSE:
                logger.debug(
                    "  r/%s post: score=%d  ratio=%.2f  w=%.3f  contrib=%.4f  title=%.60s",
                    subreddit, karma, ratio, w, w * (ratio - 0.5) * 2.0,
                    pd.get("title", ""),
                )

        if weight_sum == 0.0:
            logger.warning("Reddit: all posts have zero karma for r/%s", subreddit)
            return None

        raw_signal = signal_sum / weight_sum
        clamped = max(-1.0, min(1.0, raw_signal))

        result = RedditResult(
            subreddit=subreddit,
            score=clamped,
            post_count=len(posts),
            fetched_at=datetime.now(timezone.utc),
            from_cache=False,
        )
        _cache[asset] = (result, now_mono + cache_ttl)
        logger.info(
            "Reddit r/%s: score=%.4f  posts=%d",
            subreddit, result.score, result.post_count,
        )
        return result

    except Exception as exc:
        logger.warning("Reddit fetch failed for r/%s: %s", subreddit, exc)
        return None
