---
id: 06-fetcher-news
title: Cryptopanic + RSS news fetcher with URL dedup
phase: 2
depends_on: [01, 02]
parallel_with: [07, 08]
blocks: [09]
files:
  create:
    - src/fetchers/news.py
references:
  must_read:
    - CLAUDE.md (Critical Gotchas — Cryptopanic 200 req/day; Error Handling)
    - .claude/rules/fetchers.md (canonical rules — news section + common patterns)
    - docs/plan.md §8.1 (news fetcher spec)
  also_useful:
    - tasks/02-storage.md (exposes: is_news_seen, save_news, NewsSeen model)
    - tasks/05-generators.md (NewsItem dataclass lives in src/generators/types — reuse it)
exposes:
  - src.fetchers.news.fetch_news(limit: int = 20) -> list[NewsItem] (async)
---

# Task 06 — News fetcher

## Goal
Pull crypto news from Cryptopanic with RSS fallback, dedup against `news_seen`, return new items.

**Why separate from Task 03:** news has a DB dependency (dedup against `news_seen`), so it cannot start until Task 02 lands. sentiment + trending in Task 03 are pure HTTP.

## Files to create
- `src/fetchers/news.py` — single async `fetch_news(limit=20) -> list[NewsItem]`.

## Implementation notes
- Primary: `GET https://cryptopanic.com/api/developer/v2/posts/?auth_token={settings.CRYPTOPANIC_API_KEY}&kind=news&filter=hot`.
- On 429 / 5xx / timeout: fall back to RSS via `feedparser`:
  - `https://cointelegraph.com/rss`
  - `https://www.coindesk.com/arc/outboundfeeds/rss/`
- Per item:
  1. `url_hash = hashlib.sha256(url.encode()).hexdigest()`
  2. Skip if `repository.is_news_seen(url_hash)` is True.
  3. Build `NewsItem(id=url_hash, title=..., url=..., source=..., published_at=...)` (import the dataclass from `src.generators.types`).
  4. `repository.save_news(news_item)` so we never see it again.
  5. Append to return list (up to `limit`).
- **Never log the API key**, even at DEBUG.
- On total failure (Cryptopanic AND RSS both fail): log + return `[]`. Scheduler will retry next interval.

## Hand-off contract
- Task 09's `job_fetch_news` calls this every 2hr (interval set in Task 09's scheduler).
- Returned `NewsItem`s become input to `job_generate_batch` → Task 05's picker + caption.

## Acceptance criteria
- Called twice with same Cryptopanic mocked response: first call returns N items, second returns 0 (all deduped).
- With Cryptopanic mocked to 500: falls back to RSS, returns items if RSS is mocked too.
- Respects the `limit` argument (returned list ≤ limit).
- Never raises out of the function.
- `published_at` is a UTC `datetime`.
