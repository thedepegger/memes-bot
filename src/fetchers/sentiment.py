"""Fear & Greed Index fetcher.

Hits api.alternative.me (no auth) once per hour and caches the result
in-process so the scheduler can call this freely without burning the
upstream quota. Always returns a SentimentReading — never raises.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx

from src.utils.logger import logger


FNG_URL = "https://api.alternative.me/fng/?limit=1"
CACHE_TTL = timedelta(hours=1)
REQUEST_TIMEOUT = 10.0

_VALID_LABELS = {"extreme_fear", "fear", "neutral", "greed", "extreme_greed"}


@dataclass
class SentimentReading:
    score: int  # 0-100
    label: str  # extreme_fear | fear | neutral | greed | extreme_greed
    timestamp: datetime


# Module-level cache. Reset on process restart (acceptable for v1).
_cache: dict | None = None


def _safe_default() -> SentimentReading:
    return SentimentReading(score=50, label="neutral", timestamp=datetime.utcnow())


def _normalize_label(raw: str) -> str:
    """Lowercase + snake_case the Fear & Greed classification.

    Upstream returns values like 'Extreme Fear', 'Fear', 'Neutral',
    'Greed', 'Extreme Greed'. Anything we don't recognize falls back
    to 'neutral'.
    """
    label = raw.strip().lower().replace(" ", "_").replace("-", "_")
    if label not in _VALID_LABELS:
        logger.warning(f"unknown sentiment label '{raw}', defaulting to neutral")
        return "neutral"
    return label


async def fetch_sentiment() -> SentimentReading:
    """Fetch the current Fear & Greed Index.

    Cached in-process for 1 hour. On any failure, logs and returns a
    safe 'neutral / 50' default — callers should never see an exception.
    """
    global _cache

    now = datetime.utcnow()
    if _cache is not None:
        reading: SentimentReading = _cache["reading"]
        if now - _cache["fetched_at"] < CACHE_TTL:
            logger.debug("sentiment cache hit")
            return reading

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            response = await client.get(FNG_URL)
            response.raise_for_status()
            payload = response.json()

        logger.debug(f"fng raw payload: {payload}")

        data = payload.get("data") or []
        if not data:
            raise ValueError("fng response missing 'data'")

        entry = data[0]
        score = int(entry["value"])
        label = _normalize_label(entry["value_classification"])
        if not 0 <= score <= 100:
            raise ValueError(f"fng score out of range: {score}")

        reading = SentimentReading(score=score, label=label, timestamp=now)
        _cache = {"reading": reading, "fetched_at": now}
        logger.info(f"sentiment fetched: {label} ({score})")
        return reading

    except Exception as exc:
        logger.error(f"sentiment fetch failed: {exc!r}")
        return _safe_default()
