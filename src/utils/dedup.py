"""Dedup helpers for the meme bot.

See docs/plan.md §13.

`hash_topic` is the canonical implementation — do NOT re-implement
elsewhere (per .claude/rules/storage.md).
"""

from __future__ import annotations

import hashlib
import re

from src.storage import repository


# Stopwords stripped before hashing topic content words. See plan §13.
STOPWORDS: frozenset[str] = frozenset(
    {
        "the",
        "a",
        "an",
        "is",
        "to",
        "of",
        "in",
        "and",
        "as",
        "for",
        "on",
        "at",
        "by",
        "with",
    }
)


# Pre-compile the non-alphanumeric stripper. Operates on lowercase text.
_NON_ALNUM = re.compile(r"[^a-z0-9 ]")


def hash_topic(title: str) -> str:
    """Stable 16-char hex hash of the first 5 content words of `title`.

    Pipeline:
        1. lowercase
        2. strip everything except [a-z0-9 ]
        3. split, drop stopwords, take first 5
        4. SHA-1 of the joined content words
        5. return first 16 hex chars
    """
    lowered = title.lower()
    cleaned = _NON_ALNUM.sub("", lowered)
    words = cleaned.split()
    content = [w for w in words if w not in STOPWORDS][:5]
    digest = hashlib.sha1(" ".join(content).encode("utf-8")).hexdigest()
    return digest[:16]


def is_duplicate(
    template_id: str, topic_hash: str, hours: int = 48
) -> bool:
    """Thin wrapper around `repository.recently_used`."""
    return repository.recently_used(template_id, topic_hash, hours=hours)
