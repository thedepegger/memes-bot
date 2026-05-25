---
description: Rules for SQLAlchemy ORM models, SQLite session handling, and the repository layer.
globs:
  - src/storage/**
alwaysApply: false
---

# Storage Rules

## Schema source of truth

- **No migrations system in v1.** `src/storage/models.py` is the only source of truth for schema. Drop+recreate the SQLite file is the expected path pre-launch.
- Tables: `news_seen`, `candidates`, `template_usage`. Indexes on `candidates(status)`, `candidates(scheduled_for)`, `template_usage(used_at)`.

## Session management

- Build one `engine` + `SessionLocal` in `src/storage/db.py`.
- Always use the session via context manager (`with SessionLocal() as session:`); never instantiate `Session()` directly elsewhere.
- One session per logical unit of work (one job tick, one TG callback). Do not pass sessions across async boundaries that survive past the job.
- Commit explicitly. Roll back in the `except` branch before re-raising.

## Repository layer (`repository.py`)

- All DB reads/writes go through helper functions here. Other modules import from `repository`, never compose raw queries inline.
- Naming: `get_*` for reads, `save_*` / `mark_*` / `record_*` for writes.
- The `status` field on `candidates` is a state machine: `pending → approved → posted`, OR `pending → rejected`, OR `* → failed`. Only mutate via dedicated helpers (`mark_approved`, `mark_posted`, `mark_failed`, `mark_rejected`). Never `candidate.status = "..."` inline.
- `record_template_usage(template_id, topic_hash)` is called **at approval time, not generation time** — regens must not burn the dedup slot.

## Dedup support

- `news_seen.id` is a SHA-256 of the URL. Use `repository.is_news_seen(url_hash)` before inserting.
- `template_usage(template_id, topic_hash, used_at)` is the composite key. Query `repository.recently_used(template_id, topic_hash, hours=48)`.
- `topic_hash` is computed by `utils/dedup.hash_topic` — do not re-implement it elsewhere.

## Backups

- Daily backup via `sqlite3 data/memebot.db ".backup data/backup_$(date +%Y%m%d).db"` (cron, see plan §18). Code does not handle this.
