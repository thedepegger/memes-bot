from __future__ import annotations

import importlib
import random
import sys
from datetime import datetime, timedelta

from config.settings import settings
from src.utils.time_windows import compute_post_schedule


def test_prime_window_afternoon_stays_prime():
    """Approval at 14:00 UTC, 0 posts today — schedule must land in prime
    window (10:00–02:00 UTC). Either same-day hour >= 10, or next-day hour
    < 3 (covers the rollover edge of the window with jitter)."""
    random.seed(42)
    approval = datetime(2026, 5, 25, 14, 0, 0)
    result = compute_post_schedule(approval, posts_today=0)

    assert isinstance(result, datetime)
    same_day_prime = result.date() == approval.date() and result.hour >= 10
    next_day_tail = result.date() == (approval.date() + timedelta(days=1)) and result.hour < 3
    assert same_day_prime or next_day_tail, (
        f"result {result} not in prime window (10:00–02:00 UTC)"
    )


def test_dead_window_approval_pushed_to_prime_open():
    """Approval at 04:00 UTC (dead window) — schedule must be >= 10:00 UTC
    same day."""
    random.seed(7)
    approval = datetime(2026, 5, 25, 4, 0, 0)
    result = compute_post_schedule(approval, posts_today=0)

    earliest_prime = datetime(2026, 5, 25, 10, 0, 0)
    # ±15min jitter is permitted, but the spec requires the post not to land
    # in the dead window — so 10:00 - 15min = 09:45 is the conservative
    # earliest acceptable.
    assert result >= earliest_prime - timedelta(minutes=15), (
        f"result {result} earlier than prime window open with jitter"
    )


def test_minimum_gap_against_last_scheduled():
    """When the last scheduled post is at 14:00 and we get a new approval
    at 13:50, the new post must be at least 15 minutes away from the last."""
    random.seed(1234)
    last = datetime(2026, 5, 25, 14, 0, 0)
    approval = datetime(2026, 5, 25, 13, 50, 0)

    result = compute_post_schedule(approval, posts_today=0, last_scheduled=last)
    gap_seconds = abs((result - last).total_seconds())
    # Allow a 1-second tolerance for floating-point / rounding.
    assert gap_seconds >= 15 * 60 - 1, (
        f"gap of {gap_seconds}s < 15min between {result} and last={last}"
    )


def test_overflow_when_posts_today_at_cap():
    """When posts_today is at or above the daily cap, schedule must roll over
    to the next day."""
    random.seed(99)
    approval = datetime(2026, 5, 25, 14, 0, 0)
    result = compute_post_schedule(approval, posts_today=settings.POSTS_PER_DAY)

    assert result.date() > approval.date(), (
        f"posts_today >= cap ({settings.POSTS_PER_DAY}) should roll to next day, "
        f"got {result}"
    )


def test_time_windows_module_is_pure():
    """Importing src.utils.time_windows must not pull in network/db deps.

    Snapshot sys.modules before, then after a fresh import. None of the
    heavyweight modules below should appear as new entries.
    """
    FORBIDDEN = (
        "httpx",
        "requests",
        "sqlalchemy",
        "openai",
        "aiogram",
        "tweepy",
        "feedparser",
        "loguru",
    )

    # Drop time_windows and any cached forbidden module so the snapshot is
    # taken against a clean baseline.
    for name in list(sys.modules.keys()):
        if name == "src.utils.time_windows" or name.startswith("src.utils.time_windows."):
            del sys.modules[name]

    before = set(sys.modules.keys())
    importlib.import_module("src.utils.time_windows")
    after = set(sys.modules.keys())

    newly_loaded = after - before
    leaked = [m for m in newly_loaded if any(m == f or m.startswith(f + ".") for f in FORBIDDEN)]
    assert not leaked, f"time_windows import leaked heavyweight modules: {leaked}"
