"""SQLAlchemy 2 ORM models for the meme bot.

Schema source of truth — see docs/plan.md §7.

Tables:
    - news_seen        : URL-hashed dedup of fetched news items.
    - candidates       : generated meme candidates with state machine in `status`.
    - template_usage   : (template_id, topic_hash, used_at) — composite key
                         used for 48hr dedup of same template + same topic.

Notes:
    - `Candidate.status` is a plain string column. The state machine
      (pending -> approved -> posted, etc.) is enforced by repository
      helpers, NOT by DB constraints (per .claude/rules/storage.md).
    - `text_boxes` stores a JSON-serialised list[str] in a TEXT column.
      Serialisation is handled by repository helpers (json.dumps/loads).
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Index, Integer, Float, Text, DateTime, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Single declarative base for every ORM model."""

    pass


class NewsSeen(Base):
    """A news item we've already fetched. `id` is sha256(url)."""

    __tablename__ = "news_seen"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class Candidate(Base):
    """A generated meme candidate. `status` is the state machine field."""

    __tablename__ = "candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    news_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    news_title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    news_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    template_id: Mapped[str] = mapped_column(String, nullable=False)
    template_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # JSON-serialised list[str]; read/write via repository helpers.
    text_boxes: Mapped[str] = mapped_column(Text, nullable=False)
    caption: Mapped[str] = mapped_column(Text, nullable=False)
    image_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sentiment_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sentiment_label: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    tg_message_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # State machine: pending, approved, rejected, posted, failed.
    status: Mapped[str] = mapped_column(String, nullable=False)
    scheduled_for: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    posted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    tweet_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)


class TemplateUsage(Base):
    """One row per (template_id, topic_hash, used_at) — composite PK."""

    __tablename__ = "template_usage"

    template_id: Mapped[str] = mapped_column(String, primary_key=True)
    topic_hash: Mapped[str] = mapped_column(String, primary_key=True)
    used_at: Mapped[datetime] = mapped_column(DateTime, primary_key=True)


# Indexes — per docs/plan.md §7.
Index("idx_candidates_status", Candidate.status)
Index("idx_candidates_scheduled", Candidate.scheduled_for)
Index("idx_template_usage_time", TemplateUsage.used_at)
