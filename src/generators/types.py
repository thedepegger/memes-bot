"""Shared dataclasses for the generator pipeline.

Defined once here; fetchers and publishers import from this module to avoid
duplicate type definitions and drift between pipeline stages.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class NewsItem:
    """A single news headline fed into the generator pipeline."""

    id: str
    title: str
    url: str
    source: str
    published_at: datetime


@dataclass
class TemplateChoice:
    """The picker's output: which Imgflip template to render and with what text.

    `boxes` is a list of strings in the template-defined order (e.g. drake is
    `[no_this, yes_this]`). `meme.render_meme` serialises these into the
    Imgflip `boxes[i][text]` form fields preserving that order.
    """

    template_id: str
    template_name: str
    boxes: list[str]
    reasoning: str


__all__ = ["NewsItem", "TemplateChoice"]
