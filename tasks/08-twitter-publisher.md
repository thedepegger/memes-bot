---
id: 08-twitter-publisher
title: X posting via tweepy v1.1 media + v2 tweet
phase: 2
depends_on: [01, 02]
parallel_with: [06, 07]
blocks: [09]
files:
  create:
    - src/publishers/twitter.py
references:
  must_read:
    - CLAUDE.md (Critical Gotchas — v1.1 vs v2 split, 15-min gap, free-tier limits)
    - .claude/rules/publishers.md (canonical rules — twitter section, read fully)
    - docs/plan.md §8.8 (twitter module)
  also_useful:
    - tasks/02-storage.md (Candidate model, mark_posted, mark_failed, get_last_posted_at, reschedule)
exposes:
  - src.publishers.twitter.post_to_x(candidate) -> str  # tweet_id on success
  - src.publishers.twitter.TwitterRateLimitError(retry_after_seconds: int) — raised so scheduler can reschedule
---

# Task 08 — X (Twitter) posting

## Goal
Post an approved candidate to X. **Media upload uses tweepy v1.1; tweet creation uses tweepy v2.** Both are mandatory on the free tier.

**Independent from Task 07:** telegram is inbound (operator → bot), twitter is outbound (bot → X). They share zero state — wired together only by the scheduler in Task 09.

## Files to create
- `src/publishers/twitter.py`.

## Implementation notes

### Module-level clients
```python
api_v1 = tweepy.API(
    tweepy.OAuth1UserHandler(
        settings.X_API_KEY, settings.X_API_SECRET,
        settings.X_ACCESS_TOKEN, settings.X_ACCESS_TOKEN_SECRET,
    )
)
client_v2 = tweepy.Client(
    consumer_key=settings.X_API_KEY, consumer_secret=settings.X_API_SECRET,
    access_token=settings.X_ACCESS_TOKEN, access_token_secret=settings.X_ACCESS_TOKEN_SECRET,
)
```

### `TwitterRateLimitError` exception
```python
class TwitterRateLimitError(Exception):
    def __init__(self, retry_after_seconds: int):
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"rate limited; retry in {retry_after_seconds}s")
```

### `post_to_x(candidate) -> str`
1. **15-min gap pre-check**: `last = repository.get_last_posted_at()`; if `last and (utcnow() - last) < 15min`: raise `TwitterRateLimitError(retry_after_seconds=int(15*60 - (utcnow()-last).total_seconds()))`. Do not mark failed.
2. Download `candidate.image_url` to a `tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)` via `httpx`.
3. `media = api_v1.media_upload(filename=tmp.name)` → `media_id = media.media_id`.
4. `tweet = client_v2.create_tweet(text=candidate.caption, media_ids=[media_id])`.
5. Return `str(tweet.data["id"])`.
6. **`finally`**: `os.unlink(tmp.name)` — clean up the temp file even on error.

### Error handling
- `tweepy.TooManyRequests` → raise `TwitterRateLimitError(retry_after_seconds=30*60)` (30 min default unless response headers say otherwise).
- Image download failure (httpx error, non-2xx) → log, call `repository.mark_failed(candidate.id)`, return None (or raise — scheduler handles both).
- Any other tweepy error → log, `mark_failed`, return None.

### What goes in the tweet
- **`text = candidate.caption`** — that's it. No URL, no extra hashtags, no source link. The meme IS the tweet.

## Hand-off contract
- Task 09's `job_post_queue` does:
  ```python
  try:
      tweet_id = await post_to_x(c)
      repository.mark_posted(c.id, tweet_id)
  except TwitterRateLimitError as e:
      repository.reschedule(c.id, delay_seconds=e.retry_after_seconds)
  except Exception:
      log.exception(...); repository.mark_failed(c.id)
  ```
- `TwitterRateLimitError` keeps `Candidate.status == 'approved'`. Other errors flip to `failed`.

## Acceptance criteria
- With both tweepy clients mocked, `post_to_x` returns the mocked tweet id as a string.
- On simulated `TooManyRequests`: raises `TwitterRateLimitError`, does NOT mark failed.
- On 15-min gap violation: raises `TwitterRateLimitError`, does NOT attempt upload or tweet.
- Temp file is deleted even when an exception is raised mid-flow (verify with a `tmp_path` fixture or by patching `os.unlink`).
- `create_tweet` is called with `text=candidate.caption` exactly — no decoration.
