---
description: Rules for APScheduler jobs and posting time-window logic.
globs:
  - src/scheduler/**
  - src/utils/time_windows.py
alwaysApply: false
---

# Scheduler Rules

## Jobs (`src/scheduler/jobs.py`)

Three `AsyncIOScheduler` jobs, all using `interval` triggers:

| Job | Interval | Responsibility |
|---|---|---|
| `job_fetch_news` | 2 hours | Pull news, dedup against `news_seen`, persist |
| `job_generate_batch` | 4 hours | Pull recent unprocessed news, pick template + caption, render, drop to TG |
| `job_post_queue` | 15 minutes | Post `approved` candidates whose `scheduled_for <= now` to X |

- Wrap each job body in a top-level `try/except Exception` that logs and continues — a job crash must never kill the scheduler.
- `job_post_queue` **respects `WARMUP_MODE`**: returns immediately if `settings.WARMUP_MODE`.
- `job_generate_batch` walks news items in priority order, skipping any where `is_duplicate_topic(news)` or `recently_used(template_id, topic_hash)` returns True. Generate up to `CANDIDATES_PER_BATCH` (default 5) per tick.

## Posting time windows (`src/utils/time_windows.py`)

- **Prime window**: 10:00 UTC → 02:00 UTC next day (16hr).
- **Dead window**: 02:00 → 10:00 UTC. If `compute_post_schedule` is called during dead hours, return next 10:00 UTC.
- **Distribution**: `POSTS_PER_DAY` (default 9) spread evenly across 16hr ≈ every 107min. Apply ±15min random jitter so the cadence doesn't look botty.
- **Minimum gap**: 15min between posts. If a computed slot is within 15min of an existing scheduled candidate, push out by 15min and recheck.
- If `posts_already_today >= POSTS_PER_DAY`, schedule for tomorrow's 10:00 UTC + offset.

## Manual triggers (Phase 3)

- `/generate <url>` from admin in TG calls into a generation path that bypasses news fetcher — accept the URL, build a `NewsItem`, run picker + caption + render, drop a candidate. This path still respects dedup.

## Don'ts

- Don't use `cron` triggers in v1 — interval is simpler and we don't need wall-clock alignment.
- Don't make scheduler jobs depend on each other — each must be independently re-runnable.
- Don't sleep inside a job. If you need a delay, reschedule.
