# Task List — Crypto Meme Bot Build

10 tasks across 5 phases. **Tasks inside a phase are parallel-safe** (no shared files, no hidden state collision). **Phases are sequential** — wait for all tasks in phase N to complete before starting phase N+1.

Each task file is self-contained: it cites the `CLAUDE.md` sections and `.claude/rules/*.md` files an agent must read first, lists the exact files to create, and documents the public surface it exposes for downstream tasks to import.

---

## Dependency Graph

```
Phase 0 (sequential, 1 task):
    [01-foundation]
         │
         ├──────────────┬──────────────┬──────────────┐
         ▼              ▼              ▼              ▼
Phase 1 (parallel, 4 tasks):
    [02-storage]   [03-fetchers]  [04-time]    [05-generators]
         │              │                              │
         ├──────────────┤                              │
         ▼              ▼                              ▼
Phase 2 (parallel, 3 tasks):
    [06-news]      [07-telegram]              [08-twitter]
         │              │                              │
         └──────────────┴────────────┬─────────────────┘
                                     ▼
Phase 3 (sequential, 1 task):
                          [09-scheduler-main]
                                     │
                                     ▼
Phase 4 (sequential, 1 task):
                              [10-tests]
```

---

## Parallel Cohorts (what to dispatch together)

| Phase | Dispatch these in parallel | Wait for |
|---|---|---|
| 0 | `01-foundation` | — |
| 1 | `02-storage`, `03-fetchers-easy`, `04-time-windows`, `05-generators` | `01` |
| 2 | `06-fetcher-news`, `07-telegram-publisher`, `08-twitter-publisher` | `02` (all three need it); `04` (07 also needs it) |
| 3 | `09-scheduler-main` | `02–08` |
| 4 | `10-tests` | `02`, `04`, `05` minimum (more if testing later modules) |

---

## Tasks

| ID | Title | Files | Hard deps | Co-related with (context only) |
|---|---|---|---|---|
| [01](01-foundation.md) | Foundation: env files, settings, logger, LLM client, config data, package skeletons | 14 | — | All — bedrock for everything |
| [02](02-storage.md) | Storage layer + dedup utility (models + db + repository + dedup) | 5 | 01 | 06 (uses `is_news_seen`/`save_news`), 07 (uses `mark_approved`), 08 (uses `Candidate`), 09 (orchestrates), 10 (test_dedup) |
| [03](03-fetchers-easy.md) | Sentiment + trending fetchers (no DB dep) | 3 | 01 | 09 (consumes outputs) |
| [04](04-time-windows.md) | Posting schedule (prime/dead hours + jitter) | 1 | 01 | 07 (calls `compute_post_schedule`), 09 (delegates scheduling), 10 (test_time_windows) |
| [05](05-generators.md) | Picker + caption + meme renderer (LLM pipeline) | 4 | 01 | 09 (orchestrates pipeline), 10 (test_picker, test_caption) |
| [06](06-fetcher-news.md) | Cryptopanic + RSS news fetcher with URL dedup | 1 | 01, 02 | 09 (calls every 2hr) |
| [07](07-telegram-publisher.md) | aiogram approval flow (approve/regen/skip/edit) | 1 | 01, 02, 04 | 09 (bot started by main; regen reuses generators from 05) |
| [08](08-twitter-publisher.md) | X posting via tweepy v1.1 media + v2 tweet | 1 | 01, 02 | 09 (called every 15min by `job_post_queue`) |
| [09](09-scheduler-main.md) | APScheduler jobs + main entrypoint | 2 | 01, 02, 03, 04, 05, 06, 07, 08 | All — this is the wiring layer |
| [10](10-tests.md) | pytest tests + fixtures + conftest | 6 | 02, 04, 05 (per test file) | All |

---

## How to dispatch (suggested agent prompt pattern)

For each task, give the agent this stub plus the task file path:

> Read `tasks/<id>.md` end-to-end, then read every file listed under `references.must_read`. Implement exactly the files under `files.create`. Do not touch files outside that list — other tasks own them. Honor the `exposes` contract verbatim so dependent tasks can import without surprises. When done, report which files you wrote and any deviations from the task file.

Tasks within a phase have **disjoint file lists** — two agents writing in parallel will not collide. The only shared files (`__init__.py` for each package, `pyproject.toml`, `requirements.txt`) are all created by task 01.

---

## Co-relation rationale (why some files are bundled into one task)

- **Task 02 bundles `models.py + db.py + repository.py + dedup.py`** — the schema is shared knowledge; splitting would force agents to negotiate ORM column names across PRs. dedup uses repository helpers.
- **Task 05 bundles `picker.py + caption.py + meme.py`** — picker and caption both consume the shared `utils/llm.py` client and need agreement on the `TemplateChoice` shape that picker outputs and meme consumes. Splitting would risk type drift.
- **Task 09 bundles `scheduler/jobs.py + main.py`** — main bootstraps the scheduler and the telegram bot in the same event loop. They're written together.
- **Task 10 bundles all tests** — shared conftest, shared fixture file, consistent pytest style. One agent owns test conventions.

---

## What does NOT block what

- `03-fetchers-easy` (sentiment/trending) has **zero downstream blockers in Phase 1** — sentiment + trending are pure HTTP. Run them with `02` and `05` in parallel safely.
- `05-generators` does **not** depend on storage — generators are pure transformations. The scheduler in `09` is responsible for persisting candidates.
- `08-twitter-publisher` does **not** depend on `07-telegram-publisher` — they're inbound vs outbound; only `09` wires them together.
