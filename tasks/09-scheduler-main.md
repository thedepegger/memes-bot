---
id: 09-scheduler-main
title: APScheduler jobs + main entrypoint
phase: 3
depends_on: [01, 02, 03, 04, 05, 06, 07, 08]
parallel_with: []
blocks: [10]
files:
  create:
    - src/scheduler/jobs.py
    - src/main.py
references:
  must_read:
    - CLAUDE.md (Architecture, Build Phases)
    - .claude/rules/scheduler.md (canonical rules — read fully)
    - docs/plan.md §4 (architecture diagram), §8.9 (job definitions), §14 (build phases)
  also_useful:
    - Every other task's `exposes` block — this is the wiring layer; reread them all
exposes:
  - src.scheduler.jobs.build_scheduler() -> AsyncIOScheduler  # three jobs registered, not yet started
  - src.main entrypoint: `python -m src.main [--dry-run]`
---

# Task 09 — Scheduler + main entrypoint

## Goal
Wire all upstream tasks together. Three APScheduler interval jobs, plus the aiogram bot in the same event loop.

**Co-relation rationale:** main.py boots the scheduler AND the telegram bot in one asyncio runloop. Splitting forces two agents to negotiate the lifecycle. One agent owns both files.

## Files to create

### `src/scheduler/jobs.py`
Three async jobs registered on an `AsyncIOScheduler`. Each job wraps its body in `try/except Exception` so one crash never kills the scheduler.

#### `job_fetch_news` — interval 2hr
Calls `fetchers.news.fetch_news()`. News fetcher persists internally; this job just triggers it and logs counts.

#### `job_generate_batch` — interval 4hr
```
news_list = repository.get_recent_news(limit=settings.CANDIDATES_PER_BATCH)
sentiment = await fetch_sentiment()
trending = await fetch_trending()
for news in news_list:
    topic_hash = dedup.hash_topic(news.title)
    if recently_used_any_template(topic_hash): continue  # topic-only check
    template = await pick_template(news, sentiment)
    if template is None: continue
    if repository.recently_used(template.template_id, topic_hash): continue
    image_url = await render_meme(template)
    if image_url is None: continue
    caption = await write_caption(news, template, sentiment, trending)
    candidate = repository.save_candidate(...)  # status='pending'
    await telegram.drop_to_telegram(candidate)
```

#### `job_post_queue` — interval 15min
```
if settings.WARMUP_MODE:
    return
due = repository.get_approved_candidates_due_now()
for c in due:
    try:
        tweet_id = await twitter.post_to_x(c)
        repository.mark_posted(c.id, tweet_id)
    except twitter.TwitterRateLimitError as e:
        repository.reschedule(c.id, delay_seconds=e.retry_after_seconds)
    except Exception as e:
        log.exception("post failed for candidate %s", c.id)
        repository.mark_failed(c.id)
```

### `src/main.py`
- Parse `--dry-run` flag (use `argparse`).
- **Dry-run path**: skip scheduler + telegram. Call `fetch_sentiment` + `fetch_trending` + `fetch_news(limit=5)` once, run picker + meme + caption for each, print each as JSON, exit. **No DB writes** in dry-run (or write but don't drop to TG).
- **Normal path**:
  ```python
  init_db()
  bot = build_bot()
  dispatcher = build_dispatcher()
  scheduler = build_scheduler()
  scheduler.start()
  try:
      await run_polling(dispatcher, bot)
  finally:
      scheduler.shutdown(wait=False)
      await bot.session.close()
  ```
- `asyncio.run(main())` at the bottom.
- Handle SIGINT/SIGTERM via `asyncio.get_event_loop().add_signal_handler` (or rely on aiogram's polling to honor KeyboardInterrupt).

## Implementation notes
- Use `AsyncIOScheduler`, NOT `BackgroundScheduler`. Same event loop as aiogram.
- `interval` triggers (`hours=2`, `hours=4`, `minutes=15`) — `.claude/rules/scheduler.md` forbids cron triggers in v1.
- Order in main: `init_db` → build scheduler → build bot → `scheduler.start()` → `await run_polling()`. Polling blocks; scheduler ticks in the background of the same loop.

## Hand-off contract
- Task 10 (tests) does NOT test the scheduler directly. Tests target individual jobs by mocking dependencies.

## Acceptance criteria
- `python -m src.main --dry-run` prints 5 candidate JSON blobs (`{template_id, template_name, boxes, caption, image_url}`) and exits cleanly. No TG, no X.
- `python -m src.main` (with valid `.env`) boots without error. `scheduler.get_jobs()` returns 3 jobs. Bot responds to `/start` from the admin user.
- Ctrl+C shuts down both scheduler and bot cleanly (no orphan tasks, no traceback).
- A simulated `TwitterRateLimitError` during `job_post_queue` results in `reschedule` being called and `status` staying `approved`.
- A simulated exception during `job_generate_batch` for ONE news item does not stop processing of the remaining items.
