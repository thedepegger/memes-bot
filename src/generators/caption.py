"""LLM-driven chaos goblin caption writer.

Tone is pre-picked in Python via weighted random from `config/voice.json`;
the LLM never chooses tone. Output is forced lowercase, 4-15 words,
no emojis/hashtags, max 1 cashtag. On post-check violation we retry once
then return a tone-appropriate fallback so the pipeline never blocks.
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path
from typing import Any

from src.generators.types import NewsItem, TemplateChoice
from src.utils.llm import call_llm
from src.utils.logger import logger


# Load voice config once at module import.
_VOICE_PATH = Path(__file__).resolve().parents[2] / "config" / "voice.json"
with _VOICE_PATH.open("r", encoding="utf-8") as _f:
    _VOICE: dict[str, Any] = json.load(_f)

_TONE_WEIGHTS: dict[str, float] = _VOICE["tone_weights"]
_LEXICON: list[str] = _VOICE.get("lexicon_core", [])


# Same emoji regex as picker.py — kept local to avoid cross-module coupling.
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001F6FF"
    "\U0001F700-\U0001F77F"
    "\U0001F780-\U0001F7FF"
    "\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FA6F"
    "\U0001FA70-\U0001FAFF"
    "\U00002600-\U000026FF"
    "\U00002700-\U000027BF"
    "\U0001F1E6-\U0001F1FF"
    "]",
    flags=re.UNICODE,
)

# Cashtag: $ followed by 1+ letters/digits (word boundary on the $ side via
# the leading anchor handled in scanning). We count using findall.
_CASHTAG_RE = re.compile(r"\$[a-zA-Z][a-zA-Z0-9]{0,9}")

# Quote characters to strip from LLM output.
_QUOTE_CHARS = "\"'`‘’“”"


# Fallback captions keyed by tone — used when the LLM keeps producing
# off-voice output. Each is 4-15 words, lowercase, no emoji, no hashtag,
# zero cashtags. Tested to pass the same post-check as live captions.
_FALLBACKS: dict[str, str] = {
    "bull": "im in ser. wagmi for real this time",
    "bear": "down bad. cooked. ngmi probably",
    "cope": "still bullish actually. just a normal correction",
    "euphoria": "we're so back. this changes everything",
    "doom": "it's so over. nothing matters anymore",
}
_DEFAULT_FALLBACK = "down bad. cope levels critical right now"


def _pick_tone() -> str:
    """Weighted random tone choice. Deterministic via random module state."""
    tones = list(_TONE_WEIGHTS.keys())
    weights = [float(_TONE_WEIGHTS[t]) for t in tones]
    return random.choices(tones, weights=weights, k=1)[0]


def _build_system_prompt() -> str:
    """System prompt per docs/plan.md §8.5. Voice rules match config/voice.json."""
    return (
        "You are a chaos goblin crypto Twitter shitposter. You write meme captions.\n\n"
        "Voice rules (NEVER break):\n"
        "- All lowercase.\n"
        "- 4 to 15 words total.\n"
        "- No hashtags.\n"
        "- No emojis.\n"
        "- Never explain the joke.\n"
        "- Maximum 1 cashtag (like $btc or $sol). Often zero.\n"
        "- Match the meme's vibe but DO NOT describe the meme.\n\n"
        "Tone roulette: pick ONE per caption, randomly:\n"
        "- Bull: euphoric, \"im in\", \"buying\", \"wagmi\", \"few\"\n"
        "- Bear: doomer, \"down bad\", \"cooked\", \"ngmi\", \"cope\"\n"
        "- Cope: defeated bull rationalizing, \"still bullish actually\"\n"
        "- Euphoria: peak greed, \"this changes everything\", \"we're so back\"\n"
        "- Doom: pure nihilism, \"nothing matters\", \"good night sweet prince\"\n\n"
        "Approved lexicon (use sparingly, not every post):\n"
        f"{', '.join(_LEXICON)}\n\n"
        "Contradictions across posts are FEATURE not bug. You are a chaos goblin.\n\n"
        "Output the caption text ONLY. No quotes, no preamble, no explanation."
    )


def _user_message(
    news: NewsItem,
    template: TemplateChoice,
    sentiment: Any,
    trending: list[str],
    tone: str,
) -> str:
    score = getattr(sentiment, "score", "?")
    label = getattr(sentiment, "label", "?")
    trending_str = ", ".join(trending) if trending else "none"
    boxes_str = " | ".join(template.boxes)
    return (
        f"News: {news.title}\n"
        f"Meme template: {template.template_name}\n"
        f"Meme text boxes: {boxes_str}\n"
        f"Sentiment: {label} ({score}/100)\n"
        f"Trending tickers today: {trending_str}\n"
        f"Tone for this post: {tone}"
    )


def _clean(raw: str) -> str:
    """Strip surrounding whitespace and quote characters from LLM output."""
    text = (raw or "").strip()
    # Strip matching outer quotes repeatedly in case of nested.
    while len(text) >= 2 and text[0] in _QUOTE_CHARS and text[-1] in _QUOTE_CHARS:
        text = text[1:-1].strip()
    # Also strip any stray leading/trailing quote chars left over.
    text = text.strip(_QUOTE_CHARS).strip()
    return text


def _is_valid(text: str) -> bool:
    if not text:
        return False
    if text != text.lower():
        return False
    if "#" in text:
        return False
    if _EMOJI_RE.search(text):
        return False
    word_count = len(text.split())
    if word_count < 4 or word_count > 15:
        return False
    if len(_CASHTAG_RE.findall(text)) > 1:
        return False
    return True


async def write_caption(
    news: NewsItem,
    template: TemplateChoice,
    sentiment: Any,
    trending: list[str],
) -> str:
    """Generate a chaos-goblin tweet caption. Never raises — falls back on failure."""
    tone = _pick_tone()
    system = _build_system_prompt()
    user = _user_message(news, template, sentiment, trending, tone)

    raw = await call_llm(system, user, max_tokens=100, temperature=0.8)
    text = _clean(raw)

    if not _is_valid(text):
        logger.warning(
            f"caption: post-check failed (tone={tone}) raw={raw!r}; retrying once"
        )
        raw = await call_llm(system, user, max_tokens=100, temperature=0.8)
        text = _clean(raw)
        if not _is_valid(text):
            fallback = _FALLBACKS.get(tone, _DEFAULT_FALLBACK)
            logger.error(
                f"caption: retry also failed (tone={tone}) raw={raw!r}; "
                f"using fallback={fallback!r}"
            )
            return fallback

    logger.info(f"caption: produced tone={tone} text={text!r}")
    return text


__all__ = ["write_caption"]
