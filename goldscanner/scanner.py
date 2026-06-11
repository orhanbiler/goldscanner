"""Orchestrates one scan cycle: search -> dedupe -> prefilter -> score -> collect."""

from __future__ import annotations

import logging

from .client import ShopGoodwillClient
from .config import Config
from .models import Item, Score
from .store import SeenStore
from .vision import VisionScorer

log = logging.getLogger(__name__)


class Scanner:
    def __init__(
        self,
        config: Config,
        client: ShopGoodwillClient,
        store: SeenStore,
        scorer: VisionScorer | None,
        extra_sources: list | None = None,
        activity=None,
    ):
        self.config = config
        self.client = client
        self.store = store
        self.scorer = scorer
        # Each extra source exposes fetch_items() -> list[Item] (etsy, ebay, ...).
        self.extra_sources = extra_sources or []
        # Per-source diagnostics from the most recent scan, for the UI.
        self.last_source_stats: dict[str, dict] = {}
        self.activity = activity

    def _say(self, message: str, level: str = "info") -> None:
        if self.activity is not None:
            self.activity.add(message, level)

    def scan_once(self) -> list[tuple[Item, Score]]:
        """Run a full scan and return the list of newly matched (item, score)."""
        matches: list[tuple[Item, Score]] = []
        new_count = 0
        skipped = 0

        self._say("🔍 Starting a new scan…")

        for item in self._iter_new_items():
            new_count += 1
            if not self._passes_prefilter(item):
                self.store.record(item, matched=False, confidence=None, reasoning="")
                skipped += 1
                continue

            is_lot = self._looks_like_lot(item.title)
            short = item.title[:70]
            if is_lot:
                self._say(f'📦 Studying a jewelry lot — scanning its photos: "{short}"')
            else:
                self._say(f'🔎 Examining "{short}"…')

            score = self._score(item)
            matched = score.is_match and score.confidence >= self.config.min_confidence
            self.store.record(
                item,
                matched=matched,
                confidence=score.confidence,
                reasoning=score.reasoning,
                gold_type=score.gold_type,
                karat=score.karat,
                hallmark=score.hallmark,
            )
            pct = round(score.confidence * 100)
            if matched:
                self._say(
                    f'✅ Match! {pct}% — "{short}" — saved to your candidates.',
                    "success",
                )
                matches.append((item, score))
            else:
                why = (score.reasoning or "").lstrip("[Lot] ")[:90]
                self._say(f'🙈 Not a match ({pct}%) — "{short}". {why}', "muted")

        self._say(
            f"🟢 Scan complete: looked at {new_count} new listing(s), "
            f"skipped {skipped}, found {len(matches)} match(es).",
            "success" if matches else "info",
        )
        log.info(
            "Scan complete: %d new item(s) examined, %d match(es).",
            new_count,
            len(matches),
        )
        return matches

    # -- internals -----------------------------------------------------------

    def _iter_new_items(self):
        """Yield unseen items across all sources, de-duplicated this cycle."""
        seen_this_cycle: set[str] = set()
        stats: dict[str, dict] = {}
        self.last_source_stats = stats

        def fresh(items):
            for item in items:
                if not item.item_id or item.item_id in seen_this_cycle:
                    continue
                seen_this_cycle.add(item.item_id)
                if self.store.is_seen(item.item_id):
                    continue
                yield item

        # shopgoodwill search
        sg_fetched = 0
        sg_error: str | None = None
        for query in self.config.queries:
            self._say(f'🛒 Searching ShopGoodwill for "{query}"…', "muted")
            for page in range(1, self.config.pages_per_query + 1):
                try:
                    items = self.client.search(query, page=page)
                except Exception as exc:  # noqa: BLE001
                    sg_error = str(exc)
                    log.warning("search failed (query=%r page=%d): %s", query, page, exc)
                    self._say(f'⚠️ ShopGoodwill search for "{query}" failed: {exc}', "warn")
                    break
                if not items:
                    break
                sg_fetched += len(items)
                yield from fresh(items)
        stats["shopgoodwill"] = {"fetched": sg_fetched, "error": sg_error}

        # other sources (etsy, ebay) — each best-effort
        for source in self.extra_sources:
            name = getattr(source, "name", type(source).__name__.lower())
            pretty = {"etsy": "Etsy", "ebay": "eBay"}.get(name, name)
            self._say(f"🏷️ Checking {pretty}…", "muted")
            try:
                items = source.fetch_items()
                err = getattr(source, "last_error", None)
                stats[name] = {"fetched": len(items), "error": err}
                if err:
                    self._say(f"⚠️ {pretty}: {err}", "warn")
                else:
                    self._say(f"🏷️ {pretty}: found {len(items)} listing(s).", "muted")
                yield from fresh(items)
            except Exception as exc:  # noqa: BLE001
                stats[name] = {"fetched": 0, "error": str(exc)}
                log.warning("source %s failed: %s", name, exc)
                self._say(f"⚠️ {pretty} failed: {exc}", "warn")

    def _passes_prefilter(self, item: Item) -> bool:
        keywords = self.config.title_keywords
        if not keywords:
            return True
        title = item.title.lower()
        return any(kw.lower() in title for kw in keywords)

    def _looks_like_lot(self, title: str) -> bool:
        lowered = title.lower()
        return any(kw.lower() in lowered for kw in self.config.lot_keywords)

    def _score(self, item: Item) -> Score:
        if not self.config.use_ai or self.scorer is None:
            return Score.keyword_only()
        # Multi-item lots get a bigger photo budget so the model can hunt for a
        # matching bangle buried among the pieces.
        limit = (
            self.config.lot_max_images
            if self._looks_like_lot(item.title)
            else self.config.max_images_per_item
        )
        # Enrich with detail photos + the seller's description, both strong
        # evidence for the gold question (shopgoodwill only — its detail API
        # takes the bare item id).
        if item.source == "shopgoodwill":
            detail = self.client.fetch_detail(item.item_id, image_limit=limit)
            if not item.description:
                item.description = detail.get("description") or None
            for url in detail.get("images", []):
                if url not in item.image_urls:
                    item.image_urls.append(url)
        return self.scorer.score(item, max_images=limit)
