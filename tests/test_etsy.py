"""Tests for the Etsy JSON-LD parser and scanner integration (no network)."""

import os
import tempfile

from goldscanner.config import Config
from goldscanner.etsy import EtsyClient
from goldscanner.models import Item, Score
from goldscanner.scanner import Scanner
from goldscanner.store import SeenStore

SAMPLE_HTML = """
<html><head>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "ItemList",
  "itemListElement": [
    {
      "@type": "ListItem",
      "position": 1,
      "item": {
        "@type": "Product",
        "name": "Antique Victorian Gold Filled Bangle with Black Enamel",
        "url": "https://www.etsy.com/listing/123456789/antique-victorian-bangle?ref=search",
        "image": "https://i.etsystatic.com/abc/il_794xN.123.jpg",
        "offers": {"@type": "Offer", "price": "245.00", "priceCurrency": "USD"}
      }
    },
    {
      "@type": "Product",
      "name": "Victorian Rolled Gold Bangle Taille d'Epargne",
      "url": "//www.etsy.com/listing/987654321/victorian-bangle",
      "image": ["//i.etsystatic.com/xyz/il_794xN.987.jpg"],
      "offers": {"@type": "AggregateOffer", "lowPrice": "180", "highPrice": "220"}
    }
  ]
}
</script>
<script type="application/ld+json">{"@type":"BreadcrumbList","itemListElement":[]}</script>
<script type="application/ld+json">not json at all</script>
</head><body></body></html>
"""


def test_parse_listings_from_jsonld():
    items = EtsyClient.parse_listings(SAMPLE_HTML)
    assert len(items) == 2

    first = items[0]
    assert first.item_id == "etsy-123456789"
    assert first.source == "etsy"
    assert first.title.startswith("Antique Victorian")
    assert first.current_price == "245.00"
    assert first.url == "https://www.etsy.com/listing/123456789/antique-victorian-bangle"
    assert first.image_urls == ["https://i.etsystatic.com/abc/il_794xN.123.jpg"]

    second = items[1]
    assert second.item_id == "etsy-987654321"
    assert second.current_price == "180"  # lowPrice fallback
    assert second.url.startswith("https://")  # protocol-relative fixed
    assert second.image_urls == ["https://i.etsystatic.com/xyz/il_794xN.987.jpg"]


def test_parse_handles_garbage():
    assert EtsyClient.parse_listings("<html>nothing here</html>") == []
    assert EtsyClient.parse_listings("") == []


class FakeSG:
    def search(self, query, page=1, page_size=40):
        return []

    def fetch_detail_images(self, item_id, limit=5):
        return []


class FakeSource:
    def __init__(self, items):
        self.items = items
        self.calls = 0

    def fetch_items(self):
        self.calls += 1
        return self.items


class FakeScorer:
    def score(self, item, max_images=None):
        return Score(True, 0.9, "match")


def test_scanner_includes_extra_source_items():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    store = SeenStore(path)
    try:
        etsy_item = Item(
            item_id="etsy-1",
            title="Victorian gold bangle black enamel",
            source="etsy",
            image_urls=["https://i.etsystatic.com/x.jpg"],
            url="https://www.etsy.com/listing/1/x",
        )
        ebay_item = Item(
            item_id="ebay-9",
            title="Antique gold filled bangle",
            source="ebay",
            image_urls=["https://i.ebayimg.com/y.jpg"],
            url="https://www.ebay.com/itm/9",
        )
        cfg = Config(
            queries=["bangle"],
            title_keywords=["bangle"],
            use_ai=True,
            email_enabled=False,
            pages_per_query=1,
        )
        src = FakeSource([etsy_item, ebay_item])
        scanner = Scanner(cfg, FakeSG(), store, FakeScorer(), extra_sources=[src])

        matches = scanner.scan_once()
        assert sorted(m[0].item_id for m in matches) == ["ebay-9", "etsy-1"]
        assert src.calls == 1
        assert store.get_item("etsy-1")["source"] == "etsy"
        assert store.get_item("ebay-9")["source"] == "ebay"
        assert scanner.scan_once() == []  # deduped
    finally:
        store.close()
        os.remove(path)


def test_scanner_records_source_stats():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    store = SeenStore(path)
    try:
        good = FakeSource(
            [Item(item_id="etsy-5", title="bangle", source="etsy",
                  image_urls=["https://x/i.jpg"], url="https://x")]
        )
        good.name = "etsy"

        class Bad:
            name = "ebay"

            def fetch_items(self):
                raise RuntimeError("oauth failed")

        cfg = Config(queries=[], title_keywords=[], use_ai=False,
                     email_enabled=False)
        scanner = Scanner(cfg, FakeSG(), store, None, extra_sources=[good, Bad()])
        scanner.scan_once()

        stats = scanner.last_source_stats
        assert stats["etsy"] == {"fetched": 1, "error": None}
        assert stats["ebay"]["fetched"] == 0
        assert "oauth failed" in stats["ebay"]["error"]
        assert stats["shopgoodwill"]["fetched"] == 0
    finally:
        store.close()
        os.remove(path)


def test_failing_source_does_not_break_scan():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    store = SeenStore(path)
    try:
        class Boom:
            def fetch_items(self):
                raise RuntimeError("blocked")

        cfg = Config(queries=[], title_keywords=[], use_ai=False, email_enabled=False)
        scanner = Scanner(cfg, FakeSG(), store, None, extra_sources=[Boom()])
        assert scanner.scan_once() == []  # no crash
    finally:
        store.close()
        os.remove(path)


def test_old_db_schema_gets_source_column():
    """Databases created before multi-source get the column added."""
    import sqlite3

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        conn = sqlite3.connect(path)
        conn.execute(
            """
            CREATE TABLE items (
                item_id TEXT PRIMARY KEY, title TEXT, price TEXT, end_time TEXT,
                num_bids INTEGER, image_url TEXT, url TEXT,
                matched INTEGER NOT NULL DEFAULT 0, confidence REAL, reasoning TEXT,
                status TEXT NOT NULL DEFAULT 'new',
                first_seen REAL NOT NULL, updated REAL NOT NULL
            )
            """
        )
        conn.execute(
            "INSERT INTO items (item_id, title, matched, first_seen, updated) "
            "VALUES ('old1', 'Old item', 1, 0, 0)"
        )
        conn.commit()
        conn.close()

        store = SeenStore(path)  # triggers migration
        row = store.get_item("old1")
        assert row["source"] == "shopgoodwill"
        store.close()
    finally:
        os.remove(path)
