"""Data structures for listings and scoring results."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Item:
    """A single shopgoodwill listing, normalized from the search API."""

    item_id: str
    title: str
    current_price: str | None = None
    end_time: str | None = None
    num_bids: int | None = None
    # Fully-qualified image URLs (thumbnail first, then any detail photos).
    image_urls: list[str] = field(default_factory=list)

    @property
    def url(self) -> str:
        return f"https://shopgoodwill.com/item/{self.item_id}"


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
