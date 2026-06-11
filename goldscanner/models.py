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
    # Seller-provided description text (plain text, source-dependent).
    description: str | None = None


@dataclass
class Score:
    """The vision model's verdict on an item."""

    is_match: bool
    confidence: float
    reasoning: str
    # Structured gold assessment (driven by visual tells, not the stamp).
    gold_type: str = "unknown"  # solid_gold | gold_filled | gold_plated | not_gold | unknown
    karat: str | None = None      # e.g. "14K", "1/20 12K GF"
    hallmark: str | None = None   # stamp text actually read in the photos
    # Antique-period read: the primary value signal.
    looks_victorian: bool = False
    antique_style: str | None = None  # e.g. "Victorian buckle bangle"

    @classmethod
    def keyword_only(cls) -> "Score":
        """A pass-through score for when AI scoring is disabled."""
        return cls(is_match=True, confidence=1.0, reasoning="Keyword match (AI scoring disabled).")
