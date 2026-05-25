"""Crypto news fetcher: Cryptopanic primary + RSS fallback.

Hits Cryptopanic's developer API for hot news; on rate-limit, 5xx, timeout,
or any network failure falls back to the Cointelegraph + Coindesk RSS feeds
via `feedparser`. Items are URL-hashed and deduped against `news_seen` so
the scheduler can poll freely without re-emitting work the generator has
already chewed through. Never raises out of `fetch_news` — total upstream
failure returns `[]` so the APScheduler job tolerates an empty interval.

Cryptopanic free tier is capped at 200 req/day; scheduler polls every 2hr
(12/day) per CLAUDE.md Critical Gotchas. **Never log the API key**, even
at DEBUG.
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone
from typing import Any

import feedparser
import httpx

from config.settings import settings
from src.generators.types import NewsItem
from src.storage.db import engine as _engine, init_db as _init_db
from src.storage.repository import is_news_seen, save_news
from src.utils.logger import logger


CRYPTOPANIC_URL = "https://cryptopanic.com/api/developer/v2/posts/"
RSS_FEEDS: list[tuple[str, str]] = [
    ("Cointelegraph", "https://cointelegraph.com/rss"),
    ("Coindesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
]
REQUEST_TIMEOUT = 10.0


def _url_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


def _parse_cryptopanic_datetime(raw: Any) -> datetime:
    """Best-effort ISO8601 -> aware UTC datetime. Falls back to utcnow()."""
    if isinstance(raw, str) and raw:
        try:
            # Cryptopanic emits e.g. '2026-05-25T10:00:00Z'
            cleaned = raw.replace("Z", "+00:00")
            dt = datetime.fromisoformat(cleaned)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except (ValueError, TypeError):
            pass
    return datetime.now(timezone.utc)


def _parse_rss_datetime(entry: Any) -> datetime:
    """Coerce a feedparser entry's `published_parsed` to aware UTC datetime."""
    published_parsed = getattr(entry, "published_parsed", None)
    if published_parsed:
        try:
            return datetime(*published_parsed[:6], tzinfo=timezone.utc)
        except (TypeError, ValueError):
            pass
    return datetime.now(timezone.utc)


async def _fetch_cryptopanic() -> list[dict[str, Any]] | None:
    """Hit Cryptopanic. Returns the raw `results` list on success.

    Returns `None` on 429 / 5xx / timeout / network failure so the caller
    knows to fall back to RSS. Raises nothing — never logs the API key.
    """
    params = {
        "auth_token": settings.CRYPTOPANIC_API_KEY,
        "kind": "news",
        "filter": "hot",
    }

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.get(CRYPTOPANIC_URL, params=params)
            status = response.status_code
            if status == 429 or status >= 500:
                logger.warning(
                    f"cryptopanic returned HTTP {status}, falling back to RSS"
                )
                return None
            response.raise_for_status()
            payload = response.json()
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        logger.warning(f"cryptopanic network failure: {exc!r}, falling back to RSS")
        return None
    except Exception as exc:
        logger.error(f"cryptopanic fetch failed: {exc!r}, falling back to RSS")
        return None

    results = payload.get("results")
    if not isinstance(results, list):
        logger.warning("cryptopanic payload missing 'results' list")
        return None
    return results


def _build_item_from_cryptopanic(raw: dict[str, Any]) -> NewsItem | None:
    """Project a Cryptopanic post into a NewsItem. Returns None if malformed."""
    url = raw.get("url")
    title = raw.get("title")
    if not isinstance(url, str) or not url:
        return None
    if not isinstance(title, str) or not title:
        return None

    source_field = raw.get("source") or {}
    if isinstance(source_field, dict):
        source = source_field.get("title") or "cryptopanic"
    else:
        source = "cryptopanic"

    return NewsItem(
        id=_url_hash(url),
        title=title,
        url=url,
        source=str(source),
        published_at=_parse_cryptopanic_datetime(raw.get("published_at")),
    )


def _fetch_rss_sync() -> list[NewsItem]:
    """Parse the RSS fallback feeds. Synchronous; called via to_thread."""
    items: list[NewsItem] = []
    for source_name, feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
        except Exception as exc:
            logger.error(f"rss parse failed for {source_name}: {exc!r}")
            continue

        entries = getattr(feed, "entries", None) or []
        for entry in entries:
            url = getattr(entry, "link", None)
            title = getattr(entry, "title", None)
            if not isinstance(url, str) or not url:
                continue
            if not isinstance(title, str) or not title:
                continue
            items.append(
                NewsItem(
                    id=_url_hash(url),
                    title=title,
                    url=url,
                    source=source_name,
                    published_at=_parse_rss_datetime(entry),
                )
            )
    return items


async def _fetch_rss() -> list[NewsItem]:
    """Async wrapper: feedparser is blocking, so run it in a thread."""
    try:
        return await asyncio.to_thread(_fetch_rss_sync)
    except Exception as exc:
        logger.error(f"rss fallback failed: {exc!r}")
        return []


async def fetch_news(limit: int = 20) -> list[NewsItem]:
    """Fetch up to `limit` fresh, deduped crypto news items.

    Tries Cryptopanic first, falls back to RSS on rate-limit / 5xx /
    network failure. Items already in `news_seen` are skipped. New
    items are persisted to `news_seen` so the next call won't re-emit
    them. On total failure, logs and returns `[]`.
    """
    new_items: list[NewsItem] = []

    try:
        raw_results = await _fetch_cryptopanic()

        candidates: list[NewsItem] = []
        if raw_results is not None:
            for raw in raw_results:
                if not isinstance(raw, dict):
                    continue
                item = _build_item_from_cryptopanic(raw)
                if item is not None:
                    candidates.append(item)
            logger.info(f"cryptopanic returned {len(candidates)} valid items")
        else:
            candidates = await _fetch_rss()
            logger.info(f"rss fallback returned {len(candidates)} items")

        pool_refreshed = False
        for item in candidates:
            if len(new_items) >= limit:
                break
            try:
                if is_news_seen(item.id):
                    continue
                save_news(item)
                new_items.append(item)
            except Exception as exc:
                # If the underlying sqlite file was swapped under us (e.g.
                # tests that remove + recreate the db mid-process), the
                # pooled connection holds a stale fd that surfaces as
                # "readonly database" or "no such table". Dispose the
                # pool, re-create the schema, and retry the row once.
                exc_str = str(exc)
                stale_signature = (
                    "readonly database" in exc_str
                    or "no such table" in exc_str
                )
                if not pool_refreshed and stale_signature:
                    pool_refreshed = True
                    try:
                        _engine.dispose()
                        _init_db()
                        if is_news_seen(item.id):
                            continue
                        save_news(item)
                        new_items.append(item)
                        continue
                    except Exception as retry_exc:
                        logger.error(
                            f"failed to persist news item {item.url} "
                            f"after pool refresh: {retry_exc!r}"
                        )
                        continue
                logger.error(f"failed to persist news item {item.url}: {exc!r}")
                continue

        logger.info(
            f"fetch_news: {len(new_items)} new items (limit={limit})"
        )
        return new_items

    except Exception as exc:
        logger.error(f"fetch_news unexpected failure: {exc!r}")
        return []
