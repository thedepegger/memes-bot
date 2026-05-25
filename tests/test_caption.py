from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.generators.caption import write_caption
from src.generators.types import NewsItem, TemplateChoice


# Tone names defined in config/voice.json — the caption module must select one
# of these in Python and inject it into the prompt.
KNOWN_TONES = ("bull", "bear", "cope", "euphoria", "doom")


def _make_news() -> NewsItem:
    payload = dict(
        id="news_001",
        title="Ethereum overtakes Solana in DEX volume after merge upgrade",
        url="https://example.com/eth-vs-sol",
        source="CoinDesk",
        published_at=datetime(2026, 5, 24, 10, 0, 0, tzinfo=timezone.utc),
    )
    try:
        return NewsItem(**payload)
    except TypeError:
        payload.pop("published_at", None)
        return NewsItem(**payload)


def _make_template() -> TemplateChoice:
    """Build a TemplateChoice. We try the typical kwargs first."""
    base = dict(
        template_id="181913649",
        boxes=["buying the dip again", "selling at the top finally"],
    )
    for extra in ({"reasoning": "drake rotation"}, {}):
        try:
            return TemplateChoice(**base, **extra)
        except TypeError:
            continue
    # Last resort: positional
    return TemplateChoice("181913649", ["buying the dip again", "selling at the top finally"])


def _make_sentiment(label: str = "neutral", score: float = 0.0):
    return SimpleNamespace(
        label=label,
        score=score,
        summary="market sentiment is mixed",
        confidence=0.7,
    )


@pytest.mark.asyncio
async def test_write_caption_happy_path():
    news = _make_news()
    template = _make_template()
    sentiment = _make_sentiment()

    with patch(
        "src.generators.caption.call_llm",
        new=AsyncMock(return_value="down bad ser. buying anyway"),
    ):
        result = await write_caption(news, template, sentiment, trending=["btc", "eth"])

    assert result == "down bad ser. buying anyway"


@pytest.mark.asyncio
async def test_write_caption_voice_violation_falls_back():
    """Both responses break voice rules (emoji, hashtag, uppercase).

    The caption module retries once, then must return a fallback that
    obeys all voice constraints. It must NEVER raise.
    """
    news = _make_news()
    template = _make_template()
    sentiment = _make_sentiment()

    bad = "BTC TO THE MOON 🚀🚀 #wagmi #bullish"
    with patch(
        "src.generators.caption.call_llm",
        new=AsyncMock(side_effect=[bad, bad]),
    ):
        result = await write_caption(news, template, sentiment, trending=["btc"])

    # No emoji (basic check: only ASCII text expected).
    assert all(ord(c) < 128 for c in result), f"non-ASCII / emoji in fallback: {result!r}"
    # No hashtag.
    assert "#" not in result
    # All lowercase (allowing punctuation).
    assert result == result.lower(), f"fallback not lowercase: {result!r}"
    # Word count 4–15.
    word_count = len(result.split())
    assert 4 <= word_count <= 15, f"fallback word count {word_count} not in [4,15]: {result!r}"


@pytest.mark.asyncio
async def test_write_caption_tone_picked_in_python():
    """The tone is chosen in Python (not by the LLM) and must appear in the
    prompt that gets sent to call_llm."""
    news = _make_news()
    template = _make_template()
    sentiment = _make_sentiment()

    with patch(
        "src.generators.caption.call_llm",
        new=AsyncMock(return_value="down bad ser. buying anyway"),
    ) as mock_llm:
        await write_caption(news, template, sentiment, trending=["btc"])

    # Collect every string argument from every call.
    all_text = ""
    for call in mock_llm.await_args_list:
        for arg in call.args:
            if isinstance(arg, str):
                all_text += arg
        for value in call.kwargs.values():
            if isinstance(value, str):
                all_text += value

    lowered = all_text.lower()
    assert any(tone in lowered for tone in KNOWN_TONES), (
        f"no known tone {KNOWN_TONES} found in prompt"
    )


@pytest.mark.asyncio
async def test_write_caption_word_count_enforcement():
    """First response is too short (2 words). Either the second response wins,
    or the module falls back to a tone-keyed default. Both are acceptable —
    we just require a 4–15 word, voice-clean string."""
    news = _make_news()
    template = _make_template()
    sentiment = _make_sentiment()

    with patch(
        "src.generators.caption.call_llm",
        new=AsyncMock(side_effect=["too short", "down bad ser. buying anyway"]),
    ):
        result = await write_caption(news, template, sentiment, trending=["btc"])

    assert isinstance(result, str)
    assert result == result.lower()
    assert "#" not in result
    assert all(ord(c) < 128 for c in result)
    word_count = len(result.split())
    assert 4 <= word_count <= 15, f"word count {word_count}: {result!r}"
