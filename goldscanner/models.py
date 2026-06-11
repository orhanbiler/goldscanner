"""Data structures for listings and scoring results."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Item:
    """A single listing, normalized from any source (shopgoodwill, etsy, ...)."""

    item_id: str
    title: str
    source: str = "shopgoodwill"
    current_price: str | None = None
    end_time: str | None = None
    num_bids: int | None = None
    # Fully-qualified image URLs (thumbnail first, then any detail photos).
    image_urls: list[str] = field(default_factory=list)
    # Link to the listing page. Set by the source client.
    url: str = ""


@dataclass
class Score:
    """The vision model's verdict on an item."""

    is_match: bool
    confidence: float
    reasoning: str

    @classmethod
    def keyword_only(cls) -> "Score":
        """A pass-through score for when AI scoring is disabled."""
        return cls(is_match=True, confidence=1.0, reasoning="Keyword match (AI scoring disabled).")
