"""X (Twitter) publisher — posts approved candidates to X.

Critical split: media upload uses tweepy v1.1; tweet creation uses v2.
Both are mandatory on the free tier. See CLAUDE.md "Critical Gotchas".

Exposes:
- `post_to_x(candidate) -> str` — returns tweet_id on success.
- `TwitterRateLimitError` — raised on 15-min gap violation or X 429.
  Scheduler (Task 09) catches and calls `repository.reschedule(...)`.
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta
from typing import Optional

import httpx
import tweepy

from config.settings import settings
from src.storage import repository
from src.utils.logger import logger


# -- module-level clients ----------------------------------------------------

api_v1 = tweepy.API(
    tweepy.OAuth1UserHandler(
        settings.X_API_KEY,
        settings.X_API_SECRET,
        settings.X_ACCESS_TOKEN,
        settings.X_ACCESS_TOKEN_SECRET,
    )
)

client_v2 = tweepy.Client(
    consumer_key=settings.X_API_KEY,
    consumer_secret=settings.X_API_SECRET,
    access_token=settings.X_ACCESS_TOKEN,
    access_token_secret=settings.X_ACCESS_TOKEN_SECRET,
)


# -- exceptions --------------------------------------------------------------


class TwitterRateLimitError(Exception):
    """Raised when posting must be deferred.

    `retry_after_seconds` tells the scheduler how far to push out
    `candidate.scheduled_for`. Candidate stays in `approved` state — do not
    mark failed.
    """

    def __init__(self, retry_after_seconds: int):
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"rate limited; retry in {retry_after_seconds}s")


# -- main entry point --------------------------------------------------------


_MIN_GAP_SECONDS = 15 * 60
_RATE_LIMIT_BACKOFF_SECONDS = 30 * 60


async def post_to_x(candidate) -> Optional[str]:
    """Post a candidate to X.

    Flow:
      1. 15-min gap pre-check vs last posted candidate.
      2. Download image to temp file via httpx.
      3. Upload media via tweepy v1.1.
      4. Create tweet via tweepy v2 with caption + media_id.
      5. Always unlink temp file in `finally`.

    Returns the tweet id (str) on success; None on non-rate-limit failure
    (after marking the candidate failed). Raises `TwitterRateLimitError`
    on rate-limit conditions — caller reschedules.
    """
    # 1. 15-min gap pre-check. Do NOT mark failed here — scheduler reschedules.
    last = repository.get_last_posted_at()
    if last is not None:
        elapsed = datetime.utcnow() - last
        if elapsed < timedelta(seconds=_MIN_GAP_SECONDS):
            wait = int(_MIN_GAP_SECONDS - elapsed.total_seconds())
            # Clamp to at least 1 so callers don't pass zero/negative downstream.
            wait = max(wait, 1)
            logger.info(
                f"post_to_x: 15-min gap not met for candidate {candidate.id} "
                f"(elapsed={elapsed.total_seconds():.0f}s); deferring {wait}s"
            )
            raise TwitterRateLimitError(retry_after_seconds=wait)

    # 2. Download image to temp file.
    tmp_path: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            async with httpx.AsyncClient(timeout=30.0) as http:
                resp = await http.get(candidate.image_url)
                resp.raise_for_status()
                with open(tmp_path, "wb") as f:
                    f.write(resp.content)
        except httpx.HTTPError as e:
            logger.error(
                f"post_to_x: image download failed for candidate "
                f"{candidate.id} ({candidate.image_url}): {e}"
            )
            repository.mark_failed(candidate.id)
            return None

        # 3. Upload media via v1.1.
        try:
            media = api_v1.media_upload(filename=tmp_path)
            media_id = media.media_id
        except tweepy.TooManyRequests as e:
            logger.warning(
                f"post_to_x: rate-limited on media_upload for candidate "
                f"{candidate.id}: {e}"
            )
            raise TwitterRateLimitError(
                retry_after_seconds=_RATE_LIMIT_BACKOFF_SECONDS
            )
        except tweepy.TweepyException as e:
            logger.error(
                f"post_to_x: media_upload failed for candidate "
                f"{candidate.id}: {e}"
            )
            repository.mark_failed(candidate.id)
            return None

        # 4. Create tweet via v2 — caption only, no URL/decoration.
        try:
            tweet = client_v2.create_tweet(
                text=candidate.caption,
                media_ids=[media_id],
            )
        except tweepy.TooManyRequests as e:
            logger.warning(
                f"post_to_x: rate-limited on create_tweet for candidate "
                f"{candidate.id}: {e}"
            )
            raise TwitterRateLimitError(
                retry_after_seconds=_RATE_LIMIT_BACKOFF_SECONDS
            )
        except tweepy.TweepyException as e:
            logger.error(
                f"post_to_x: create_tweet failed for candidate "
                f"{candidate.id}: {e}"
            )
            repository.mark_failed(candidate.id)
            return None

        # 5. Extract tweet id.
        tweet_id = str(tweet.data["id"])
        logger.info(
            f"post_to_x: posted candidate {candidate.id} as tweet {tweet_id}"
        )
        return tweet_id

    finally:
        # 6. Always clean up temp file, even on exception.
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                # Already gone or never existed — fine.
                pass
