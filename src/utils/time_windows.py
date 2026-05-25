"""Posting time-window utility.

Pure datetime helpers for deciding when an approved candidate should post.
No DB access, no I/O, no logging, no sleep — keep it pure.

Prime window: 10:00 UTC -> 02:00 UTC next day (16 hours).
Dead window:  02:00 UTC -> 10:00 UTC. Approvals landing here defer to next 10:00 UTC.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta

from config.settings import settings

# Prime window constants (UTC).
_PRIME_START_HOUR = 10  # inclusive
_PRIME_END_HOUR = 2     # exclusive (next-day 02:00 UTC)
_PRIME_WINDOW_MINUTES = 16 * 60  # 10:00 -> 02:00 next day
_JITTER_MINUTES = 15
_MIN_GAP_MINUTES = 15
_MAX_GAP_ITERATIONS = 3


def _prime_base_for(approval_time: datetime) -> datetime:
    """Return the 10:00 UTC anchor that approval_time's slot should be measured against.

    - If approval is at/after 10:00 UTC on day D, base is D @ 10:00.
    - If approval is before 10:00 UTC (dead hours early morning), base is same D @ 10:00.
    - If approval is between 02:00 and 10:00, that's dead hours → next 10:00 UTC.
      (Same-day 10:00 covers both "before 02:00 -> shouldn't happen because that's still
      prime spillover" and "02:00-10:00 dead" since both push to today's 10:00.)
    - If approval is between 00:00 and 02:00, that is still prime window spillover from
      the previous day; we treat the base as the previous day @ 10:00 so slot math lines
      up with the 16-hour window, but the resulting slot will fall in [10:00, 02:00].
    """
    # Prime spillover: 00:00 - 02:00 UTC belongs to the previous day's window.
    if approval_time.hour < _PRIME_END_HOUR:
        prev_day = approval_time.date() - timedelta(days=1)
        return datetime(prev_day.year, prev_day.month, prev_day.day, _PRIME_START_HOUR, 0, 0)
    # Same-day 10:00 UTC anchor for everything from 02:00 onward.
    return datetime(
        approval_time.year,
        approval_time.month,
        approval_time.day,
        _PRIME_START_HOUR,
        0,
        0,
    )


def _tomorrow_base(approval_time: datetime) -> datetime:
    """Return tomorrow's 10:00 UTC anchor relative to approval_time's date."""
    tomorrow = approval_time.date() + timedelta(days=1)
    return datetime(tomorrow.year, tomorrow.month, tomorrow.day, _PRIME_START_HOUR, 0, 0)


def _slot_for(base: datetime, posts_today: int) -> datetime:
    """Compute the jittered slot offset within the prime window.

    Clamps to the base anchor (prime start) as a lower bound so jitter never
    pushes a slot back into dead hours.
    """
    target_count = max(1, settings.POSTS_PER_DAY)
    base_interval = _PRIME_WINDOW_MINUTES // target_count  # ~107 min for 9 posts
    slot_offset = posts_today * base_interval
    jitter = random.randint(-_JITTER_MINUTES, _JITTER_MINUTES)
    candidate = base + timedelta(minutes=slot_offset + jitter)
    return candidate if candidate >= base else base


def _enforce_min_gap(candidate: datetime, last_scheduled: datetime | None) -> datetime:
    """Push the slot out in 15-min increments if it lands within the min-gap window."""
    if last_scheduled is None:
        return candidate
    for _ in range(_MAX_GAP_ITERATIONS):
        delta_minutes = abs((candidate - last_scheduled).total_seconds()) / 60.0
        if delta_minutes >= _MIN_GAP_MINUTES:
            return candidate
        candidate = candidate + timedelta(minutes=_MIN_GAP_MINUTES)
    return candidate


def compute_post_schedule(
    approval_time: datetime,
    posts_today: int,
    last_scheduled: datetime | None = None,
) -> datetime:
    """Return the UTC datetime at which this approved candidate should be posted.

    Rules:
    - Prime window is 10:00 UTC to 02:00 UTC next day (16hr).
    - Dead hours (02:00 - 10:00 UTC) defer to the next 10:00 UTC anchor.
    - Posts are spread evenly across the window with ±15 min jitter.
    - Minimum 15-min gap from `last_scheduled` is enforced (capped iterations).
    - Overflow (`posts_today >= POSTS_PER_DAY`) rolls to tomorrow's 10:00 UTC base + offset 0.

    Pure function — no DB, no I/O, no logging.
    """
    if posts_today >= settings.POSTS_PER_DAY:
        base = _tomorrow_base(approval_time)
        candidate = _slot_for(base, posts_today=0)
        return _enforce_min_gap(candidate, last_scheduled)

    # Dead hours: 02:00 <= hour < 10:00 → defer to today's 10:00 UTC.
    if _PRIME_END_HOUR <= approval_time.hour < _PRIME_START_HOUR:
        base = datetime(
            approval_time.year,
            approval_time.month,
            approval_time.day,
            _PRIME_START_HOUR,
            0,
            0,
        )
    else:
        base = _prime_base_for(approval_time)

    candidate = _slot_for(base, posts_today)
    return _enforce_min_gap(candidate, last_scheduled)
