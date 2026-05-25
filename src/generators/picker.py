"""LLM-driven template picker.

Given a news item + market sentiment, asks the LLM to pick the best Imgflip
template from `config/templates.json` and fill its text boxes. Output is
strict JSON; on parse or rule violation we retry once with a stricter prompt
and then give up (return None) so the scheduler can skip the news item.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from src.generators.types import NewsItem, TemplateChoice
from src.utils.llm import call_llm
from src.utils.logger import logger


# Load template pool once at module import.
_TEMPLATES_PATH = Path(__file__).resolve().parents[2] / "config" / "templates.json"
with _TEMPLATES_PATH.open("r", encoding="utf-8") as _f:
    _TEMPLATE_POOL: list[dict[str, Any]] = json.load(_f)


# Emoji detection covers the standard Unicode pictographic ranges plus a few
# common dingbat/symbol blocks. Conservative — any hit means reject.
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001F6FF"  # symbols & pictographs, transport
    "\U0001F700-\U0001F77F"  # alchemical
    "\U0001F780-\U0001F7FF"  # geometric shapes ext
    "\U0001F800-\U0001F8FF"  # supplemental arrows-C
    "\U0001F900-\U0001F9FF"  # supplemental symbols and pictographs
    "\U0001FA00-\U0001FA6F"  # chess, etc.
    "\U0001FA70-\U0001FAFF"  # symbols & pictographs ext-A
    "\U00002600-\U000026FF"  # misc symbols
    "\U00002700-\U000027BF"  # dingbats
    "\U0001F1E6-\U0001F1FF"  # regional indicator (flags)
    "]",
    flags=re.UNICODE,
)


def _build_system_prompt(pool: list[dict[str, Any]]) -> str:
    """System prompt per docs/plan.md §8.4 with the pool embedded as JSON."""
    template_list_json = json.dumps(pool, indent=2)
    return (
        "You are a meme template selector for crypto Twitter.\n\n"
        "Given a news headline and current market sentiment, you must:\n"
        "1. Pick the BEST template from the pool below.\n"
        "2. Generate text for each box, matching the template's structure exactly.\n\n"
        "Template pool:\n"
        f"{template_list_json}\n\n"
        "Rules:\n"
        "- Each text box: max 60 characters.\n"
        "- All lowercase.\n"
        "- No emojis, no hashtags.\n"
        "- Be specific to the news (mention the token/event when relevant).\n"
        "- Pick template whose structure matches the news angle:\n"
        "  - Comparison/rotation news -> drake or distracted_boyfriend\n"
        "  - Dilemma news -> two_buttons\n"
        "  - Hot take needed -> change_my_mind or expanding_brain\n"
        "  - Disaster/hack/rug -> this_is_fine or disaster_girl\n"
        "  - Sentiment swing -> wojak variants\n\n"
        "Output JSON only, no markdown fences:\n"
        "{\n"
        '  "template_id": "...",\n'
        '  "template_name": "...",\n'
        '  "boxes": ["text for box 0", "text for box 1", ...],\n'
        '  "reasoning": "one sentence why this template"\n'
        "}"
    )


def _stricter_system_prompt(pool: list[dict[str, Any]]) -> str:
    return (
        _build_system_prompt(pool)
        + "\n\nCRITICAL: JSON ONLY, NO PROSE, NO MARKDOWN FENCES. "
        "Reply with exactly one JSON object and nothing else."
    )


def _user_message(news: NewsItem, sentiment: Any) -> str:
    score = getattr(sentiment, "score", "?")
    label = getattr(sentiment, "label", "?")
    return (
        f"News: {news.title}\n"
        f"URL: {news.url}\n"
        f"Source: {news.source}\n"
        f"Current sentiment: {label} ({score}/100)"
    )


def _valid_box(text: str) -> bool:
    if not isinstance(text, str):
        return False
    if len(text) > 60:
        return False
    if text != text.lower():
        return False
    if "#" in text:
        return False
    if _EMOJI_RE.search(text):
        return False
    return True


def _parse_choice(raw: str) -> TemplateChoice | None:
    """Strict json.loads with shape validation. Returns None on any problem."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None

    if not isinstance(data, dict):
        return None

    try:
        template_id = str(data["template_id"])
        template_name = str(data["template_name"])
        boxes_raw = data["boxes"]
        reasoning = str(data.get("reasoning", ""))
    except (KeyError, TypeError):
        return None

    if not isinstance(boxes_raw, list) or not all(isinstance(b, str) for b in boxes_raw):
        return None

    return TemplateChoice(
        template_id=template_id,
        template_name=template_name,
        boxes=list(boxes_raw),
        reasoning=reasoning,
    )


async def pick_template(
    news: NewsItem,
    sentiment: Any,
    exclude_template_ids: list[str] = [],
) -> TemplateChoice | None:
    """Pick a meme template + fill text boxes for the given news + sentiment.

    Returns `None` if the LLM produces unparseable JSON twice in a row, or if
    a box fails post-checks twice in a row. Caller (scheduler) skips the news
    item on `None`.
    """
    pool = [t for t in _TEMPLATE_POOL if str(t.get("id")) not in set(exclude_template_ids)]
    if not pool:
        logger.warning("picker: no templates available after exclusion; returning None")
        return None

    system = _build_system_prompt(pool)
    user = _user_message(news, sentiment)

    raw = await call_llm(system, user, max_tokens=500, temperature=0.8)
    choice = _parse_choice(raw)

    if choice is None:
        logger.warning("picker: JSON parse failed, retrying with stricter prompt")
        stricter = _stricter_system_prompt(pool)
        raw = await call_llm(stricter, user, max_tokens=500, temperature=0.8)
        choice = _parse_choice(raw)
        if choice is None:
            logger.error(f"picker: second JSON parse failed for news id={news.id}; giving up")
            return None

    if not all(_valid_box(b) for b in choice.boxes):
        logger.warning(
            f"picker: box post-check failed for news id={news.id}, retrying once "
            f"(boxes={choice.boxes!r})"
        )
        stricter = _stricter_system_prompt(pool)
        raw = await call_llm(stricter, user, max_tokens=500, temperature=0.8)
        retry = _parse_choice(raw)
        if retry is None or not all(_valid_box(b) for b in retry.boxes):
            logger.error(
                f"picker: post-check failed twice for news id={news.id}; giving up"
            )
            return None
        choice = retry

    logger.info(
        f"picker: chose template={choice.template_name} ({choice.template_id}) "
        f"for news id={news.id}"
    )
    return choice


__all__ = ["pick_template"]
