"""Repository layer — all DB reads/writes for the bot go through here.

Helpers commit explicitly and roll back in the `except` branch before
re-raising. The `Candidate.status` state machine is enforced here, not
by DB constraints (per .claude/rules/storage.md).

Downstream tasks (06, 07, 08, 09) import these functions by name — the
signatures in this file are a hard contract.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select, func

from src.storage.db import SessionLocal
from src.storage.models import Candidate, NewsSeen, TemplateUsage
from src.utils.logger import logger


# -- news_seen ---------------------------------------------------------------


def is_news_seen(url_hash: str) -> bool:
    """Return True if a news item with this URL hash has already been recorded."""
    with SessionLocal() as session:
        row = session.get(NewsSeen, url_hash)
        return row is not None


def save_news(news_item) -> None:
    """Insert a news item into `news_seen`.

    `news_item` is duck-typed: any object with attributes
    `id`, `title`, `url`, `source` works. This keeps the repository
    free of a hard dependency on the (not-yet-built) fetchers' NewsItem
    dataclass.
    """
    with SessionLocal() as session:
        try:
            row = NewsSeen(
                id=news_item.id,
                title=news_item.title,
                url=news_item.url,
                source=getattr(news_item, "source", None),
                fetched_at=datetime.utcnow(),
            )
            session.add(row)
            session.commit()
        except Exception:
            session.rollback()
            raise


def get_recent_news(limit: int) -> list[NewsSeen]:
    """Return the most-recently-fetched news items, newest first."""
    with SessionLocal() as session:
        stmt = (
            select(NewsSeen)
            .order_by(NewsSeen.fetched_at.desc())
            .limit(limit)
        )
        return list(session.scalars(stmt).all())


# -- candidates --------------------------------------------------------------


def save_candidate(
    news_id: Optional[str],
    news_title: Optional[str],
    news_url: Optional[str],
    template_id: str,
    template_name: Optional[str],
    text_boxes: list[str],
    caption: str,
    image_url: Optional[str],
    sentiment_score: Optional[float],
    sentiment_label: Optional[str],
    tg_message_id: Optional[int] = None,
) -> Candidate:
    """Persist a freshly-generated candidate in `pending` state.

    `text_boxes` is a list[str]; we json-encode into the Text column.
    Returns the persisted (detached) Candidate.
    """
    with SessionLocal() as session:
        try:
            candidate = Candidate(
                news_id=news_id,
                news_title=news_title,
                news_url=news_url,
                template_id=template_id,
                template_name=template_name,
                text_boxes=json.dumps(text_boxes),
                caption=caption,
                image_url=image_url,
                sentiment_score=sentiment_score,
                sentiment_label=sentiment_label,
                generated_at=datetime.utcnow(),
                tg_message_id=tg_message_id,
                status="pending",
            )
            session.add(candidate)
            session.commit()
            session.refresh(candidate)
            session.expunge(candidate)
            return candidate
        except Exception:
            session.rollback()
            raise


def get_approved_candidates_due_now() -> list[Candidate]:
    """Approved candidates whose `scheduled_for` is now or in the past."""
    now = datetime.utcnow()
    with SessionLocal() as session:
        stmt = (
            select(Candidate)
            .where(
                Candidate.status == "approved",
                Candidate.scheduled_for.isnot(None),
                Candidate.scheduled_for <= now,
            )
            .order_by(Candidate.scheduled_for.asc())
        )
        return list(session.scalars(stmt).all())


def get_last_posted_at() -> Optional[datetime]:
    """Return the timestamp of the most recently posted candidate, or None."""
    with SessionLocal() as session:
        stmt = select(func.max(Candidate.posted_at)).where(
            Candidate.status == "posted"
        )
        return session.scalar(stmt)


def posts_today_count() -> int:
    """Count of candidates posted today (UTC midnight cutoff)."""
    today_start = datetime.utcnow().replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    with SessionLocal() as session:
        stmt = select(func.count()).select_from(Candidate).where(
            Candidate.status == "posted",
            Candidate.posted_at.isnot(None),
            Candidate.posted_at >= today_start,
        )
        result = session.scalar(stmt)
        return int(result or 0)


def mark_approved(candidate_id: int, scheduled_for: datetime) -> None:
    """Transition: pending -> approved. Sets scheduled_for."""
    with SessionLocal() as session:
        try:
            candidate = session.get(Candidate, candidate_id)
            if candidate is None:
                logger.warning(
                    f"mark_approved: candidate {candidate_id} not found"
                )
                return
            candidate.status = "approved"
            candidate.scheduled_for = scheduled_for
            session.commit()
        except Exception:
            session.rollback()
            raise


def mark_rejected(candidate_id: int, reason: Optional[str] = None) -> None:
    """Transition: pending -> rejected. `reason` is logged, not stored (v1)."""
    with SessionLocal() as session:
        try:
            candidate = session.get(Candidate, candidate_id)
            if candidate is None:
                logger.warning(
                    f"mark_rejected: candidate {candidate_id} not found"
                )
                return
            candidate.status = "rejected"
            session.commit()
            if reason:
                logger.info(
                    f"candidate {candidate_id} rejected: {reason}"
                )
        except Exception:
            session.rollback()
            raise


def mark_posted(candidate_id: int, tweet_id: str) -> None:
    """Transition: approved -> posted. Records tweet_id + posted_at."""
    with SessionLocal() as session:
        try:
            candidate = session.get(Candidate, candidate_id)
            if candidate is None:
                logger.warning(
                    f"mark_posted: candidate {candidate_id} not found"
                )
                return
            candidate.status = "posted"
            candidate.tweet_id = tweet_id
            candidate.posted_at = datetime.utcnow()
            session.commit()
        except Exception:
            session.rollback()
            raise


def mark_failed(candidate_id: int) -> None:
    """Transition: * -> failed."""
    with SessionLocal() as session:
        try:
            candidate = session.get(Candidate, candidate_id)
            if candidate is None:
                logger.warning(
                    f"mark_failed: candidate {candidate_id} not found"
                )
                return
            candidate.status = "failed"
            session.commit()
        except Exception:
            session.rollback()
            raise


def reschedule(candidate_id: int, delay_seconds: int) -> None:
    """Push an approved candidate's `scheduled_for` forward by N seconds.

    If `scheduled_for` is unset, base the new time on `datetime.utcnow()`.
    """
    with SessionLocal() as session:
        try:
            candidate = session.get(Candidate, candidate_id)
            if candidate is None:
                logger.warning(
                    f"reschedule: candidate {candidate_id} not found"
                )
                return
            base = candidate.scheduled_for or datetime.utcnow()
            candidate.scheduled_for = base + timedelta(seconds=delay_seconds)
            session.commit()
        except Exception:
            session.rollback()
            raise


# -- template_usage (dedup) --------------------------------------------------


def record_template_usage(template_id: str, topic_hash: str) -> None:
    """Record one (template_id, topic_hash) use at utcnow().

    Called at APPROVAL time from Task 07's approve handler — never from a
    generator (regens would otherwise burn the dedup slot).
    See .claude/rules/storage.md.
    """
    with SessionLocal() as session:
        try:
            row = TemplateUsage(
                template_id=template_id,
                topic_hash=topic_hash,
                used_at=datetime.utcnow(),
            )
            session.add(row)
            session.commit()
        except Exception:
            session.rollback()
            raise


def recently_used(
    template_id: str, topic_hash: str, hours: int = 48
) -> bool:
    """True if (template_id, topic_hash) has a usage row within the last N hours."""
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    with SessionLocal() as session:
        stmt = (
            select(TemplateUsage)
            .where(
                TemplateUsage.template_id == template_id,
                TemplateUsage.topic_hash == topic_hash,
                TemplateUsage.used_at >= cutoff,
            )
            .limit(1)
        )
        return session.scalars(stmt).first() is not None


# -- telegram publisher helpers (Task 07) ------------------------------------


def get_candidate(candidate_id: int) -> Optional[Candidate]:
    """Fetch a single candidate by id, or None if not present.

    Returned object is detached from the session so callers can safely
    read its attributes outside the `with` block.
    """
    with SessionLocal() as session:
        candidate = session.get(Candidate, candidate_id)
        if candidate is None:
            return None
        session.expunge(candidate)
        return candidate


def set_tg_message_id(candidate_id: int, tg_message_id: int) -> None:
    """Persist the Telegram message id returned by `bot.send_photo`."""
    with SessionLocal() as session:
        try:
            candidate = session.get(Candidate, candidate_id)
            if candidate is None:
                logger.warning(
                    f"set_tg_message_id: candidate {candidate_id} not found"
                )
                return
            candidate.tg_message_id = tg_message_id
            session.commit()
        except Exception:
            session.rollback()
            raise


def update_caption(candidate_id: int, new_caption: str) -> None:
    """Overwrite the candidate's caption text (used by the TG edit flow)."""
    with SessionLocal() as session:
        try:
            candidate = session.get(Candidate, candidate_id)
            if candidate is None:
                logger.warning(
                    f"update_caption: candidate {candidate_id} not found"
                )
                return
            candidate.caption = new_caption
            session.commit()
        except Exception:
            session.rollback()
            raise


def get_last_scheduled() -> Optional[datetime]:
    """Return the latest `scheduled_for` across approved or posted candidates.

    Used by the TG approve handler to enforce a 15-minute minimum gap
    between consecutive scheduled posts.
    """
    with SessionLocal() as session:
        stmt = select(func.max(Candidate.scheduled_for)).where(
            Candidate.status.in_(("approved", "posted")),
            Candidate.scheduled_for.isnot(None),
        )
        return session.scalar(stmt)


def expire_stale_pending(hours: int = 24) -> int:
    """Mark any `pending` candidate older than N hours as `rejected` (expired).

    Returns the number of rows transitioned. Called on bot startup so the
    queue never accumulates dead drops the operator never approved.
    """
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    with SessionLocal() as session:
        try:
            stmt = select(Candidate).where(
                Candidate.status == "pending",
                Candidate.generated_at < cutoff,
            )
            stale = list(session.scalars(stmt).all())
            for candidate in stale:
                candidate.status = "rejected"
            session.commit()
            count = len(stale)
            if count:
                logger.info(
                    f"expire_stale_pending: marked {count} candidates "
                    f"as rejected (expired, >{hours}h old)"
                )
            return count
        except Exception:
            session.rollback()
            raise
