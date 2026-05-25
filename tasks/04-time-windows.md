---
id: 04-time-windows
title: Posting schedule utility (prime/dead hours + jitter)
phase: 1
depends_on: [01]
parallel_with: [02, 03, 05]
blocks: [07, 09, 10]
files:
  create:
    - src/utils/time_windows.py
references:
  must_read:
    - CLAUDE.md (Key Decisions — prime hours; Critical Gotchas — dead hours)
    - .claude/rules/scheduler.md (canonical time-window rules)
    - docs/plan.md §8.11, §12 (posting schedule logic + edge cases)
  also_useful:
    - tasks/01-foundation.md (settings.POSTS_PER_DAY)
exposes:
  - src.utils.time_windows.compute_post_schedule(approval_time: datetime, posts_today: int, last_scheduled: datetime | None = None) -> datetime
---

# Task 04 — Posting time-window utility

## Goal
Pure datetime utility that decides when an approved candidate should post. **No DB, no I/O, no logging — keep it pure.**

## Files to create
- `src/utils/time_windows.py` — single public function `compute_post_schedule` plus private helpers.

## Logic spec
- **Prime window**: 10:00 UTC → 02:00 UTC next day (16 hours).
- **Dead window**: 02:00 → 10:00 UTC. If `approval_time` lands here, base the slot off **next 10:00 UTC** (same day if before 10:00, else tomorrow).
- **Distribution**: `settings.POSTS_PER_DAY` (default 9) spread evenly across 16hr → base interval ≈ 107 min.
- **Jitter**: ±15 min uniform random per slot (`random.randint(-15, 15)`).
- **Min gap enforcement**: if `last_scheduled` is set and the computed slot is within 15 min of it, push the new slot out by 15 min and re-check. Cap at ~3 iterations, then accept.
- **Overflow**: if `posts_today >= settings.POSTS_PER_DAY`, compute against tomorrow's 10:00 UTC base + offset 0.

## Implementation notes
- Pure function: no `print`, no `logger`, no DB access, no `sleep`.
- All datetimes are UTC (`datetime.utcnow()` is the only valid wall-clock source).
- Seed the RNG implicitly (no fixed seed in production code).

## Hand-off contract
- Task 07 (telegram approve handler) calls this with `(datetime.utcnow(), repository.posts_today_count(), last_scheduled_or_None)`.
- Task 09's `job_post_queue` does NOT call this — it just polls `scheduled_for <= now`.

## Acceptance criteria
- Called at 14:00 UTC with `posts_today=0` returns a datetime within `[10:00, 02:00 next day]`.
- Called at 04:00 UTC returns a datetime `>= 10:00 UTC same day`.
- Called with `last_scheduled = now + 5min`: result is `>= last_scheduled + 15min`.
- Called with `posts_today >= POSTS_PER_DAY`: result is at least the next calendar day.
- Importing the module touches no DB, makes no HTTP call.
