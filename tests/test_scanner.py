"""Unit tests with fakes — no network or API keys required."""

import os
import tempfile

from goldscanner.config import Config
from goldscanner.models import Item, Score
from goldscanner.scanner import Scanner
from goldscanner.store import SeenStore


class FakeClient:
    def __init__(self, pages, description=""):
        # pages: dict[query] -> list[list[Item]] (one inner list per page)
        self.pages = pages
        self.description = description
        self.detail_calls = []

    def search(self, query, page=1, page_size=40):
        per_query = self.pages.get(query, [])
        idx = page - 1
        return per_query[idx] if idx < len(per_query) else []

    def fetch_detail(self, item_id, image_limit=5):
        self.detail_calls.append(item_id)
        return {"images": [], "description": self.description}

    def download_image(self, url):
        return None


class FakeScorer:
    def __init__(self, verdicts):
        # verdicts: dict[item_id] -> Score
        self.verdicts = verdicts
        self.scored = []

    def score(self, item, max_images=None):
        self.scored.append(item.item_id)
        return self.verdicts.get(item.item_id, Score(False, 0.0, "no verdict"))


def make_store():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return SeenStore(path), path


def base_config(**kwargs):
    defaults = dict(
        queries=["bangle"],
        title_keywords=["bangle"],
        min_confidence=0.6,
        use_ai=True,
        pages_per_query=1,
        email_enabled=False,
    )
    defaults.update(kwargs)
    return Config(**defaults)


def test_matches_above_threshold():
    store, path = make_store()
    try:
        items = [
            Item(item_id="1", title="Gold filled enamel bangle"),
            Item(item_id="2", title="Plastic bangle"),
            Item(item_id="3", title="Gold ring"),  # filtered: no 'bangle'
        ]
        client = FakeClient({"bangle": [items]})
        scorer = FakeScorer(
            {
                "1": Score(True, 0.9, "looks right"),
                "2": Score(False, 0.1, "plastic"),
            }
        )
        scanner = Scanner(base_config(), client, store, scorer)

        matches = scanner.scan_once()

        assert [m[0].item_id for m in matches] == ["1"]
        # item 3 was prefiltered out, so it should never be scored
        assert "3" not in scorer.scored
    finally:
        store.close()
        os.remove(path)


def test_seen_items_are_skipped():
    store, path = make_store()
    try:
        items = [Item(item_id="1", title="Gold filled enamel bangle")]
        client = FakeClient({"bangle": [items]})
        scorer = FakeScorer({"1": Score(True, 0.95, "match")})
        scanner = Scanner(base_config(), client, store, scorer)

        first = scanner.scan_once()
        second = scanner.scan_once()

        assert len(first) == 1
        assert second == []  # already seen -> not re-scored
        assert scorer.scored == ["1"]
    finally:
        store.close()
        os.remove(path)


def test_low_confidence_is_not_a_match():
    store, path = make_store()
    try:
        items = [Item(item_id="9", title="Gold bangle maybe enamel")]
        client = FakeClient({"bangle": [items]})
        scorer = FakeScorer({"9": Score(True, 0.4, "unsure")})
        scanner = Scanner(base_config(min_confidence=0.6), client, store, scorer)

        assert scanner.scan_once() == []
    finally:
        store.close()
        os.remove(path)


def test_lot_listings_get_bigger_photo_budget():
    store, path = make_store()
    try:
        items = [
            Item(item_id="L1", title="Gold Filled Victorian Jewelry Lot"),
            Item(item_id="S1", title="Gold filled bangle"),
        ]
        client = FakeClient({"bangle": [items]})

        class RecordingScorer:
            def __init__(self):
                self.calls = {}

            def score(self, item, max_images=None):
                self.calls[item.item_id] = max_images
                return Score(True, 0.9, "[Lot] bangle in photo 2" if "Lot" in item.title else "single match")

        scorer = RecordingScorer()
        cfg = base_config(
            title_keywords=["bangle", "lot", "jewelry"],
            lot_keywords=["lot", "jewelry"],
            max_images_per_item=3,
            lot_max_images=6,
        )
        scanner = Scanner(cfg, client, store, scorer)
        matches = scanner.scan_once()

        # Lot got the bigger budget; single item the normal one.
        assert scorer.calls["L1"] == 6
        assert scorer.calls["S1"] == 3
        # Detail-image fetch used the same per-item limit.
        assert set(client.detail_calls) == {"L1", "S1"}
        assert len(matches) == 2
    finally:
        store.close()
        os.remove(path)


def test_description_fed_to_scorer_and_gold_fields_stored():
    store, path = make_store()
    try:
        items = [Item(item_id="1", title="Gold filled bangle")]
        client = FakeClient({"bangle": [items]}, description="Tested 14K, 13.7g")

        class GoldScorer:
            def __init__(self):
                self.seen_descriptions = {}

            def score(self, item, max_images=None):
                self.seen_descriptions[item.item_id] = item.description
                return Score(
                    True, 0.9, "reads 14K",
                    gold_type="solid_gold", karat="14K", hallmark="14K",
                )

        scorer = GoldScorer()
        scanner = Scanner(base_config(), client, store, scorer)
        matches = scanner.scan_once()

        # The seller description reached the model…
        assert scorer.seen_descriptions["1"] == "Tested 14K, 13.7g"
        # …and the structured gold verdict was persisted.
        row = store.get_item("1")
        assert (row["gold_type"], row["karat"], row["hallmark"]) == (
            "solid_gold", "14K", "14K",
        )
        assert len(matches) == 1
    finally:
        store.close()
        os.remove(path)


def test_ai_disabled_uses_keyword_only():
    store, path = make_store()
    try:
        items = [Item(item_id="5", title="Gold filled bangle")]
        client = FakeClient({"bangle": [items]})
        scanner = Scanner(base_config(use_ai=False), client, store, scorer=None)

        matches = scanner.scan_once()
        assert [m[0].item_id for m in matches] == ["5"]
    finally:
        store.close()
        os.remove(path)
