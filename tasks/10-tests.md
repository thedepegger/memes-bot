---
id: 10-tests
title: pytest tests + fixtures + conftest
phase: 4
depends_on: [02, 04, 05]
parallel_with: []
blocks: []
files:
  create:
    - tests/conftest.py
    - tests/test_picker.py
    - tests/test_caption.py
    - tests/test_dedup.py
    - tests/test_time_windows.py
    - tests/fixtures/sample_news.json
references:
  must_read:
    - CLAUDE.md (Commands — pytest invocations; Conventions)
    - docs/plan.md §17 (testing approach)
  also_useful:
    - tasks/02-storage.md (hash_topic, recently_used, record_template_usage)
    - tasks/04-time-windows.md (compute_post_schedule)
    - tasks/05-generators.md (pick_template, write_caption — both mocked via call_llm)
exposes: []
---

# Task 10 — Tests

## Goal
Unit tests for the four pieces the plan calls out as test-worthy. **LLM is mocked**; storage uses a temp SQLite. **No real HTTP calls.**

**Co-relation rationale:** shared `conftest.py`, shared fixture file, consistent pytest style. One agent owns test conventions.

Tests can technically start as soon as the tested module lands (test_dedup after Task 02, test_time_windows after Task 04, test_picker/test_caption after Task 05), but bundling keeps style consistent and is faster to dispatch as a single agent.

## Files to create

### `tests/conftest.py`
- Set `pytest-asyncio` mode = `"auto"` (in `pyproject.toml` or here).
- `tmp_db` fixture: swap `settings.DATABASE_PATH` to a temp file, call `init_db()`, yield, then delete the file.
- `mock_llm(monkeypatch)` fixture: patches `src.utils.llm.call_llm` to return queued responses from a list.
- `sample_news` fixture: loads `tests/fixtures/sample_news.json` as a list of dicts (or `NewsItem` instances).

### `tests/fixtures/sample_news.json`
~20 hand-curated headlines, at least one per `templates.json` `best_for` category. Fields: `id`, `title`, `url`, `source`, `published_at` (ISO 8601 UTC string).

### `tests/test_picker.py`
- With `mock_llm` returning valid JSON for the drake template: `pick_template(news, sentiment)` returns a `TemplateChoice` whose `template_id == "181913649"`.
- With `mock_llm` returning malformed JSON twice: returns `None`.
- With `mock_llm` returning a box >60 chars: retries once then returns `None`.
- `exclude_template_ids=["181913649"]` removes the drake template from the pool — assert against the captured prompt sent to `call_llm`.

### `tests/test_caption.py`
- With `mock_llm` returning `"down bad ser. buying anyway"`: caption passes voice check unchanged.
- With `mock_llm` returning `"BTC TO THE MOON 🚀 #wagmi"`: voice violation triggers retry; if retry also bad, fallback is returned (not an exception).
- Tone is picked in Python, not by LLM — assert the user message sent to `call_llm` contains the chosen tone.
- Word-count enforcement: 3-word output triggers retry; 16-word output triggers retry.

### `tests/test_dedup.py`
- Uses `tmp_db`.
- `hash_topic("Bitcoin ETF sees record inflows today")` is deterministic across calls.
- `hash_topic` is case-insensitive (Bitcoin == bitcoin).
- After `record_template_usage("t1", "h1")`, `recently_used("t1", "h1")` returns True.
- Stale row (insert with `used_at = now - 49h`): `recently_used("t1", "h1", hours=48)` returns False.
- Different `template_id` + same `topic_hash`: `recently_used` returns False.

### `tests/test_time_windows.py`
- 14:00 UTC + `posts_today=0` → result is within `[10:00 UTC, 02:00 UTC next day]`.
- 04:00 UTC (dead hours) → result `>= 10:00 UTC same day`.
- `last_scheduled = utcnow() + 5min` → result is `>= last_scheduled + 15min`.
- `posts_today >= settings.POSTS_PER_DAY` → result is on the next calendar day.
- Pure function: importing the module makes no HTTP call, opens no DB connection.

## Implementation notes
- `@pytest.mark.asyncio` on async tests.
- **Zero real network calls.** If a test risks one, fail the test (e.g. set `OPENROUTER_API_KEY=""` in `tmp_db`'s monkeypatch).
- Tests must pass from project root: `pytest`.

## Acceptance criteria
- `pytest` exits 0; all four test files green.
- `pytest -k dedup` runs only dedup tests and passes.
- `pytest -k time_windows` runs only time-window tests and passes.
- No test triggers a real HTTP request (verify by network sandbox or by patching `httpx.AsyncClient`).
