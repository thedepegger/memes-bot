"""CoinGecko trending tickers fetcher.

Hits the free /search/trending endpoint (no auth) and caches the result
in-process for 15 minutes. Returns up to 7 lowercase ticker symbols.
Always returns a list — never raises.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import httpx

from src.utils.logger import logger


TRENDING_URL = "https://api.coingecko.com/api/v3/search/trending"
CACHE_TTL = timedelta(minutes=15)
REQUEST_TIMEOUT = 10.0
MAX_TICKERS = 7


# Module-level cache. Reset on process restart (acceptable for v1).
_cache: dict | None = None


async def fetch_trending() -> list[str]:
    """Fetch top trending ticker symbols from CoinGecko.

    Returns up to 7 lowercase symbols (e.g. ['btc', 'sol', 'pepe', ...]).
    Cached in-process for 15 minutes. On any failure, logs and returns [].
    """
    global _cache

    now = datetime.utcnow()
    if _cache is not None:
        symbols: list[str] = _cache["symbols"]
        if now - _cache["fetched_at"] < CACHE_TTL:
            logger.debug("trending cache hit")
            return symbols

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.get(TRENDING_URL)
            response.raise_for_status()
            payload = response.json()

        logger.debug(f"trending raw payload: {payload}")

        coins = payload.get("coins") or []
        symbols: list[str] = []
        for entry in coins[:MAX_TICKERS]:
            item = entry.get("item") or {}
            symbol = item.get("symbol")
            if isinstance(symbol, str) and symbol:
                symbols.append(symbol.lower())

        _cache = {"symbols": symbols, "fetched_at": now}
        logger.info(f"trending fetched: {symbols}")
        return symbols

    except Exception as exc:
        logger.error(f"trending fetch failed: {exc!r}")
        return []
