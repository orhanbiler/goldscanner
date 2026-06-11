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


class FakeEtsy:
    def __init__(self, items):
        self.items = items
        self.calls = []

    def fetch_listings(self, url):
        self.calls.append(url)
        return self.items


class FakeScorer:
    def score(self, item):
        return Score(True, 0.9, "match")


def test_scanner_includes_etsy_items():
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
        cfg = Config(
            queries=["bangle"],
            title_keywords=["bangle"],
            use_ai=True,
            email_enabled=False,
            etsy_enabled=True,
            etsy_urls=["https://www.etsy.com/market/test"],
            pages_per_query=1,
        )
        etsy = FakeEtsy([etsy_item])
        scanner = Scanner(cfg, FakeSG(), store, FakeScorer(), etsy=etsy)

        matches = scanner.scan_once()
        assert [m[0].item_id for m in matches] == ["etsy-1"]
        assert etsy.calls == ["https://www.etsy.com/market/test"]

        # stored with its source, and deduped on the next scan
        row = store.get_item("etsy-1")
        assert row["source"] == "etsy"
        assert scanner.scan_once() == []
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
