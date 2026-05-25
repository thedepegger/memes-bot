---
description: Rules for news, sentiment, and trending data fetchers.
globs:
  - src/fetchers/**
alwaysApply: false
---

# Fetchers Rules

All fetchers are **async**; use `httpx.AsyncClient` with a 10s timeout. Never `requests`.

## `news.py` — Cryptopanic + RSS fallback

- Primary: `GET https://cryptopanic.com/api/developer/v2/posts/?auth_token={key}&kind=news&filter=hot`.
- **Free tier quota: 200 req/day.** We poll every 2hr (12/day). Do not lower the interval without checking quota math.
- On HTTP 429 or 5xx, fall back to RSS via `feedparser`:
  - Cointelegraph: `https://cointelegraph.com/rss`
  - Coindesk: `https://www.coindesk.com/arc/outboundfeeds/rss/`
- Dedup: `SHA-256(url)` → `news_seen.id`. Use `repository.is_news_seen` before adding.
- Return `list[NewsItem]` with `(id, title, url, source, published_at)`.

## `sentiment.py` — Fear & Greed Index

- `GET https://api.alternative.me/fng/?limit=1`.
- Updates **daily** — cache the result for 1hr in-process (simple module-level dict with timestamp).
- Returns `SentimentReading(score: int 0-100, label: str, timestamp)`. Label values: `extreme_fear | fear | neutral | greed | extreme_greed`.
- No auth required.

## `trending.py` — CoinGecko trending

- `GET https://api.coingecko.com/api/v3/search/trending`.
- Return top 7 ticker symbols as a `list[str]`, lowercased (e.g. `["btc", "sol", "pepe", ...]`).
- Used to enrich captions with cashtags when news doesn't name a specific token. Caption module decides whether to use them (chaos goblin uses cashtags sparingly).
- No auth required, but be polite — cache for 15min.

## Common patterns

- On any fetch failure: **log + return empty list / `None`**. Do not raise out of fetchers. The scheduler tolerates an empty batch and tries again next interval.
- Do not log API keys, even at DEBUG.
