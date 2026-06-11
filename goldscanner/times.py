"""Listing end-time normalization.

Sources report end times inconsistently:
  * shopgoodwill — naive ISO strings in US Pacific time (their site standard)
  * eBay         — ISO strings with a Z (UTC) suffix
  * Etsy         — no end time (fixed-price)

Normalize to a unix epoch so the frontend can render in the user's own
timezone with plain `Date` formatting.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")


def end_epoch(end_time: str | None, source: str) -> float | None:
    if not end_time:
        return None
    try:
        dt = datetime.fromisoformat(str(end_time).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        # Naive timestamps: shopgoodwill means Pacific; default others to UTC.
        dt = dt.replace(tzinfo=PACIFIC if source == "shopgoodwill" else timezone.utc)
    return dt.timestamp()


def with_end_ts(items: list[dict]) -> list[dict]:
    """Add a normalized `end_ts` (unix epoch or None) to each item dict."""
    for item in items:
        item["end_ts"] = end_epoch(
            item.get("end_time"), item.get("source") or "shopgoodwill"
        )
    return items
