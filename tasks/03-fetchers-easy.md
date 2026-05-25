---
id: 03-fetchers-easy
title: Sentiment + trending fetchers (no DB dep)
phase: 1
depends_on: [01]
parallel_with: [02, 04, 05]
blocks: [09]
files:
  create:
    - src/fetchers/sentiment.py
    - src/fetchers/trending.py
references:
  must_read:
    - CLAUDE.md (Conventions — async everywhere; Error Handling)
    - .claude/rules/fetchers.md (canonical rules — read fully)
    - docs/plan.md §8.2 (sentiment), §8.3 (trending)
  also_useful:
    - tasks/01-foundation.md (settings, logger)
exposes:
  - src.fetchers.sentiment.fetch_sentiment() -> SentimentReading (async)
  - src.fetchers.sentiment.SentimentReading dataclass: (score: int 0-100, label: str, timestamp: datetime)
  - src.fetchers.trending.fetch_trending() -> list[str] (async; ≤7 lowercase symbols)
---

# Task 03 — Easy fetchers

## Goal
Two async fetchers with zero DB dependency: Fear & Greed Index and CoinGecko trending tickers. **Both have in-process caches** so the scheduler can call them freely.

## Files to create

### `src/fetchers/sentiment.py`
- `SentimentReading` dataclass at module top.
- Async `fetch_sentiment() -> SentimentReading`.
- `GET https://api.alternative.me/fng/?limit=1`.
- Parse `data[0].value` (int 0-100) and `data[0].value_classification` (normalize to lowercase snake: `extreme_fear | fear | neutral | greed | extreme_greed`).
- **Cache in-process for 1 hour** — module-level `_cache: dict | None` with timestamp.

### `src/fetchers/trending.py`
- Async `fetch_trending() -> list[str]`.
- `GET https://api.coingecko.com/api/v3/search/trending`.
- Return top 7 ticker symbols lowercased.
- **Cache in-process for 15 minutes.**

## Implementation notes
- `httpx.AsyncClient` with `timeout=10.0`. Never `requests`.
- On any failure: log + return a safe default — `SentimentReading(score=50, label="neutral", timestamp=now)` for sentiment, `[]` for trending. **Do not raise.**
- Do not log raw API response bodies at INFO — only at DEBUG, and never log auth headers.

## Hand-off contract
- Task 05 (`caption.py`) imports `fetch_trending` to enrich captions.
- Task 09 (`job_generate_batch`) imports both.
- Cache state lives in-process; restart resets it (fine for v1).

## Acceptance criteria
- `python -c "import asyncio; from src.fetchers.sentiment import fetch_sentiment; print(asyncio.run(fetch_sentiment()))"` prints a SentimentReading.
- Second call within 1hr returns the cached value (no second HTTP request — verify by mocking the client).
- `fetch_trending` returns ≤7 lowercased strings.
- Both functions return safe defaults on simulated network failure rather than raising.
