---
id: 02-storage
title: Storage layer + dedup utility (models + db + repository + dedup)
phase: 1
depends_on: [01]
parallel_with: [03, 04, 05]
blocks: [06, 07, 08, 09, 10]
files:
  create:
    - src/storage/models.py
    - src/storage/db.py
    - src/storage/repository.py
    - src/utils/dedup.py
references:
  must_read:
    - CLAUDE.md (Conventions, Critical Gotchas, Error Handling)
    - .claude/rules/storage.md (canonical rules for this task — read fully)
    - docs/plan.md §7 (DB schema), §8.10 (dedup module), §13 (dedup logic)
  also_useful:
    - tasks/01-foundation.md (settings + logger contract)
exposes:
  - src.storage.models — NewsSeen, Candidate, TemplateUsage (SQLAlchemy 2 declarative)
  - src.storage.db.SessionLocal — sessionmaker; ONLY entry point for sessions
  - src.storage.db.init_db() — creates all tables (idempotent)
  - src.storage.repository helpers:
      - is_news_seen(url_hash) -> bool
      - save_news(news_item) -> None
      - save_candidate(news_id, news_title, news_url, template_id, template_name, text_boxes, caption, image_url, sentiment_score, sentiment_label, tg_message_id=None) -> Candidate
      - get_recent_news(limit) -> list[NewsSeen]
      - get_approved_candidates_due_now() -> list[Candidate]
      - get_last_posted_at() -> datetime | None
      - posts_today_count() -> int
      - mark_approved(candidate_id, scheduled_for) -> None
      - mark_rejected(candidate_id, reason=None) -> None
      - mark_posted(candidate_id, tweet_id) -> None
      - mark_failed(candidate_id) -> None
      - reschedule(candidate_id, delay_seconds) -> None
      - record_template_usage(template_id, topic_hash) -> None
      - recently_used(template_id, topic_hash, hours=48) -> bool
  - src.utils.dedup:
      - hash_topic(title: str) -> str (pure SHA-1 of first 5 content words)
      - is_duplicate(template_id, topic_hash, hours=48) -> bool  # delegates to repository.recently_used
---

# Task 02 — Storage layer + dedup utility

## Goal
SQLAlchemy ORM matching `docs/plan.md` §7, a session helper, a repository layer that hides raw queries, and the dedup utility.

**Co-relation rationale:** schema is shared knowledge across models + db + repository; dedup queries the DB via repository. Splitting forces agents to negotiate column names across PRs. One agent owns all four files.

## Files to create
- `src/storage/models.py` — `NewsSeen`, `Candidate`, `TemplateUsage` per §7. Include all three indexes. SQLAlchemy 2 style (`Mapped[...]`, `mapped_column(...)`). Single `Base = declarative_base()`.
- `src/storage/db.py` — engine from `settings.DATABASE_PATH`, `SessionLocal = sessionmaker(...)`, `init_db()` that calls `Base.metadata.create_all`. Ensure `data/` directory exists at import time (`Path(...).parent.mkdir(parents=True, exist_ok=True)`).
- `src/storage/repository.py` — every helper listed in `exposes` above. Each opens a session via context manager, commits, returns plain detached objects where avoidable.
- `src/utils/dedup.py` — `hash_topic` (lowercase, strip stopwords per §13, SHA-1 of first 5 content words, return first 16 hex chars). Stopwords list lives here. `is_duplicate` is a thin wrapper that calls `repository.recently_used`.

## Implementation notes
- `Candidate.status` is a string column; **enforce the state machine via repository helpers, NOT via DB constraints** in v1.
- `text_boxes` stores JSON-serialised `list[str]` — use `Text` column with `json.dumps`/`json.loads` in repository helpers (or a SQLAlchemy `TypeDecorator`).
- `record_template_usage` is called from Task 07's approve handler — **never from any generator** (see `.claude/rules/storage.md`).
- All datetimes are `datetime.utcnow()`. Never local time.
- `posts_today_count` = candidates with `status='posted'` AND `posted_at >= today_at_00_utc`.

## Hand-off contract
Other tasks MUST NOT mutate `Candidate.status` or `template_usage` rows directly — they go through repository helpers. The downstream agents (06, 07, 08, 09) are reading the `exposes` list above as their integration contract; do not rename or drop functions without updating the list.

## Acceptance criteria
- `python -c "from src.storage.db import init_db; init_db()"` creates a fresh SQLite at `settings.DATABASE_PATH` with three tables and three indexes (verify via `sqlite3 ... ".schema"`).
- `hash_topic("Bitcoin ETF sees $100M inflows today")` returns a stable 16-char hex string; same input → same output.
- `recently_used("t1", "h1", hours=48)` on fresh DB returns False.
- After `record_template_usage("t1", "h1")`, `recently_used("t1", "h1")` returns True.
- All datetime fields use UTC.
