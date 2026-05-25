from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.generators.picker import pick_template
from src.generators.types import NewsItem


def _make_news() -> NewsItem:
    """Build a NewsItem using only the fields the type is documented to expose.

    We try the most common keyword args first and fall back to positional if
    the dataclass differs. Keep this defensive so a small surface drift
    doesn't break every picker test."""
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
        # Fall back without published_at if the schema doesn't take it
        payload.pop("published_at", None)
        return NewsItem(**payload)


def _make_sentiment(label: str = "neutral", score: float = 0.0):
    """Duck-typed sentiment reading. The picker should only read .label /
    .score / .summary attributes; a SimpleNamespace satisfies that."""
    return SimpleNamespace(
        label=label,
        score=score,
        summary="market sentiment is mixed",
        confidence=0.7,
    )


@pytest.mark.asyncio
async def test_pick_template_happy_path():
    news = _make_news()
    sentiment = _make_sentiment()

    drake_response = json.dumps(
        {
            "template_id": "181913649",
            "boxes": [
                "buying the dip again",
                "selling at the top finally",
            ],
            "reasoning": "drake fits the rotation theme",
        }
    )

    with patch(
        "src.generators.picker.call_llm", new=AsyncMock(return_value=drake_response)
    ) as mock_llm:
        result = await pick_template(news, sentiment)

    assert result is not None
    assert result.template_id == "181913649"
    # The picker must parse and surface the boxes from the LLM JSON.
    assert hasattr(result, "boxes")
    assert list(result.boxes) == [
        "buying the dip again",
        "selling at the top finally",
    ]
    assert mock_llm.await_count == 1


@pytest.mark.asyncio
async def test_pick_template_malformed_json_twice_returns_none():
    news = _make_news()
    sentiment = _make_sentiment()

    with patch(
        "src.generators.picker.call_llm",
        new=AsyncMock(side_effect=["not json", "still not json"]),
    ):
        result = await pick_template(news, sentiment)

    assert result is None


@pytest.mark.asyncio
async def test_pick_template_box_rule_violation_returns_none():
    """Two consecutive responses violate the >60 char box rule.

    The picker retries once; after the second violation, returns None.
    """
    news = _make_news()
    sentiment = _make_sentiment()

    long_text = "x" * 80  # > 60 chars, breaks the box rule
    bad_response = json.dumps(
        {
            "template_id": "181913649",
            "boxes": [long_text, "ok short box"],
            "reasoning": "violates box rule",
        }
    )

    with patch(
        "src.generators.picker.call_llm",
        new=AsyncMock(side_effect=[bad_response, bad_response]),
    ):
        result = await pick_template(news, sentiment)

    assert result is None


@pytest.mark.asyncio
async def test_pick_template_exclude_filters_pool():
    """When exclude_template_ids is provided, the excluded id must not appear
    in the prompt the picker sends to the LLM."""
    news = _make_news()
    sentiment = _make_sentiment()

    # We don't care what the LLM returns here — the assertion is on what
    # was sent in. Return None-ish so the test ends quickly.
    with patch(
        "src.generators.picker.call_llm", new=AsyncMock(return_value="not json")
    ) as mock_llm:
        await pick_template(news, sentiment, exclude_template_ids=["181913649"])

    # Concatenate every positional + keyword string argument from every call.
    all_text = ""
    for call in mock_llm.await_args_list:
        for arg in call.args:
            if isinstance(arg, str):
                all_text += arg
        for value in call.kwargs.values():
            if isinstance(value, str):
                all_text += value

    assert "181913649" not in all_text
