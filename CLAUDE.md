# Crypto Meme Bot

Automated pipeline: fetch crypto news + sentiment → generate memes via Imgflip templates with chaos-goblin captions → queue in private Telegram channel for one-tap operator approval → auto-post to X on schedule.

Target: 8-10 posts/day on free X API tier (500 posts/month cap).

## Quick Reference

- **Full build plan**: `docs/plan.md` (single source of truth — read once when onboarding, then trust this file + `.claude/rules/` for day-to-day work).
- **Modular rules**: `.claude/rules/` (path-scoped instructions for `src/generators/`, `src/publishers/`, etc. — auto-load alongside this file).
- **Build order**: `docs/plan.md` §22 file-by-file list. Do not skip ahead.

## Tech Stack

- Python 3.11+
- `aiogram` v3 (Telegram), `tweepy` v4 (X API), `httpx` (async HTTP)
- `APScheduler` v3, `SQLAlchemy` ORM + SQLite stdlib
- LLM via **OpenRouter** (OpenAI-compatible SDK), default `anthropic/claude-haiku-4.5`
- `pydantic-settings` for config, `loguru` for logs, `feedparser` for RSS fallback

## Commands

```bash
# Setup
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                # then fill in keys

# Run
python -m src.main                  # full pipeline (scheduler + telegram bot)
python -m src.main --dry-run        # phase 0: generate 5 sample memes, skip TG/X

# Test
pytest                              # all tests
pytest tests/test_picker.py         # single file
pytest -k dedup                     # filter by name

# DB ops (no migrations system — schema lives in src/storage/models.py)
sqlite3 data/memebot.db ".schema"   # inspect
sqlite3 data/memebot.db ".backup data/backup_$(date +%Y%m%d).db"
```

## Project Structure

```
src/
├── main.py                 # entrypoint: boots scheduler + tg bot
├── fetchers/               # news.py, sentiment.py, trending.py
├── generators/             # picker.py (LLM → template), caption.py, meme.py (imgflip render)
├── publishers/             # telegram.py (approval flow), twitter.py (X posting)
├── storage/                # db.py, models.py, repository.py
├── scheduler/              # jobs.py (APScheduler cron defs)
└── utils/                  # logger.py, dedup.py, time_windows.py, llm.py (shared LLM client)

config/
├── settings.py             # pydantic-settings, env-driven
├── templates.json          # imgflip template pool (id + boxes + best_for tags)
└── voice.json              # chaos goblin tone weights + lexicon
```

## Architecture

```
scheduler ──► fetch (news + sentiment + trending)
           ──► LLM picks template + writes caption
           ──► imgflip renders image
           ──► tg drops candidate with [Approve][Regen][Skip][Edit] buttons
           ──► operator approves on phone
           ──► queued candidate auto-posts to X in next slot
```

Three APScheduler jobs (`src/scheduler/jobs.py`):
- `job_fetch_news` — every 2hr
- `job_generate_batch` — every 4hr (5 candidates per batch, expect ~2 approved → 9/day)
- `job_post_queue` — every 15min (posts approved candidates due now)

## Key Decisions (locked)

- **Telegram-first review.** Every meme passes through operator approval before X. Single admin via `TELEGRAM_ADMIN_USER_ID` — **hard-check on every handler, silently reject others.**
- **Imgflip templates only** in v1. No AI image gen. Paid tier ($9.99/mo) mandatory — free tier watermarks.
- **`WARMUP_MODE=true` for first 2 weeks.** Bot generates + drops to TG but `job_post_queue` no-ops. Operator manually copies approved memes to X. Flip to `false` after warmup.
- **Single LLM client** in `src/utils/llm.py`, shared by picker + caption. Model swap = one env var (`LLM_MODEL`).
- **SQLite + SQLAlchemy, no migrations.** Schema in `models.py` is source of truth. Drop+recreate is fine pre-launch.
- **Topic+template dedup window: 48hr.** Recorded at **approval time, not generation** — regens shouldn't burn the slot.
- **Prime posting hours: 10:00 → 02:00 UTC.** Dead hours 02:00 → 10:00 UTC; queue for next 10:00 UTC if approval lands there.

## Critical Gotchas

- **X media upload uses v1.1 API; tweet creation uses v2.** Both required. `tweepy.API.media_upload(filename)` → grab `media_id` → `tweepy.Client.create_tweet(text=caption, media_ids=[media_id])`.
- **Caption goes in tweet text, not as link to image.** The meme IS the tweet. No URL in caption body.
- **15-minute minimum gap between X posts.** Free tier has undocumented rate limits; enforce in scheduler, don't just hope.
- **Imgflip `success: false` is not an exception** — check response JSON. Do not retry same template; skip candidate.
- **OpenRouter requires custom headers** for ranking attribution: `HTTP-Referer` (from `OPENROUTER_APP_URL`) + `X-Title` (from `OPENROUTER_APP_NAME`). Set once in `utils/llm.py` client init.
- **Telegram inline-button emojis ≠ tweet emojis.** TG UI buttons can use `✓ 🔄 ⏭ ✏` because Telegram renders them as glyphs. Chaos goblin voice **forbids emojis in actual tweet captions** — strip/reject in caption post-check.
- **Cryptopanic free tier = 200 req/day.** We poll every 2hr (12/day). Do not crank the interval down without re-checking quota.
- **Telegram edit flow** is stateful: track `{admin_user_id: candidate_id}` in memory with 5-min timeout. Clear after edit text received.
- **`status` field on `candidates`** is the state machine: `pending` → `approved` → `posted`, or `pending` → `rejected`, or `*` → `failed`. Never mutate outside `storage/repository.py` helpers.

## Conventions

- **Async everywhere** in fetchers/generators/publishers. Use `httpx.AsyncClient`, never `requests`.
- **No emojis in code output or captions.** Telegram UI strings (button labels, status updates) are the only exception.
- **All caption text lowercase** — enforce in LLM prompts AND post-check in `generators/caption.py`.
- **Imports**: stdlib → third-party → local (`from src.foo import bar`). Absolute imports only.
- **Settings access**: never read env vars directly; always `from config.settings import settings`.
- **DB sessions**: use the session context manager from `storage/db.py`; never instantiate `Session()` directly.
- **Logging**: `from loguru import logger`. Log level respects `LOG_LEVEL` env var. No `print()` in committed code.
- **Naming**: snake_case modules/functions, PascalCase ORM models + dataclasses, UPPER_SNAKE for env vars.

## Error Handling

- **External API failures (Cryptopanic, Imgflip, OpenRouter, X)**: log + skip the affected batch/candidate. Do not crash the process. Scheduler retries on next interval.
- **X rate limit**: catch `tweepy.TooManyRequests`, push candidate back to queue with `scheduled_for += 30min`.
- **Imgflip render failure**: skip candidate. Do not retry same template. If user taps Regen, picker must exclude the used template.
- **LLM JSON parse failure in picker**: retry **once** with a stricter prompt. Then skip the news item.
- **Telegram handler from non-admin user**: silently reject. Do not respond, do not log identifiable info beyond user_id.
- **Don't catch broad `Exception`** outside scheduler job boundaries — let it surface in tests + dev runs.

## Build Phases (do not skip)

1. **Phase 0 — Skeleton (Day 1-2):** fetchers + generators only. Exit: `python -m src.main --dry-run` returns 5 valid Imgflip URLs with chaos-goblin captions.
2. **Phase 1 — TG approval (Day 3-4):** add `publishers/telegram.py` + storage + scheduler. `WARMUP_MODE=true`, no X. Exit: 4-5 candidates per 4hr batch, button flow works on phone, DB tracks status.
3. **Phase 2 — X auto-post (Day 5-6, after warmup):** add `publishers/twitter.py` + wire `job_post_queue`. `WARMUP_MODE=false`. Exit: approved candidates auto-post within scheduled window.
4. **Phase 3 — Polish (Week 2+):** `/stats`, `/pause`, `/resume`, error DMs to admin, expand template pool.

Smoke-test each module before moving on. Build order in `docs/plan.md` §22.

## Out of Scope (v1)

- Reply-guy bot, multi-account support, engagement analytics feedback loop, AI image gen (Flux Schnell etc.).
- DB migrations system. Drop+recreate is fine.
- Web UI / dashboard. Telegram is the only operator surface.

## Operator Notes

- Operator handle: **Depegger**. Approves from phone via Telegram channel + bot.
- Cold-start anon account: 2-week manual warmup, then auto-post. See `docs/plan.md` §15.
- Acceptance criteria: `docs/plan.md` §20 (7 consecutive days hitting all KPIs).
