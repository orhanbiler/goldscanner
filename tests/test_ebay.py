"""Tests for eBay Browse API normalization (no network)."""

from goldscanner.ebay import EbayClient


def test_normalize_full_summary():
    raw = {
        "itemId": "v1|123456789|0",
        "title": "Antique Victorian 14k Gold Bangle Black Enamel",
        "itemWebUrl": "https://www.ebay.com/itm/123456789",
        "image": {"imageUrl": "https://i.ebayimg.com/images/g/abc/s-l500.jpg"},
        "price": {"value": "499.99", "currency": "USD"},
        "bidCount": 4,
        "itemEndDate": "2026-06-15T20:00:00.000Z",
    }
    item = EbayClient._normalize(raw)
    assert item is not None
    assert item.item_id == "ebay-123456789"  # pipe id flattened
    assert item.source == "ebay"
    assert item.current_price == "499.99"
    assert item.num_bids == 4
    assert item.url == "https://www.ebay.com/itm/123456789"
    assert item.image_urls == ["https://i.ebayimg.com/images/g/abc/s-l500.jpg"]
    assert item.end_time == "2026-06-15T20:00:00.000Z"


def test_normalize_thumbnail_fallback_and_no_bids():
    raw = {
        "itemId": "987",
        "title": "Gold filled bangle",
        "itemWebUrl": "https://www.ebay.com/itm/987",
        "thumbnailImages": [{"imageUrl": "https://i.ebayimg.com/t.jpg"}],
        "price": {"value": "120.00"},
    }
    item = EbayClient._normalize(raw)
    assert item.image_urls == ["https://i.ebayimg.com/t.jpg"]
    assert item.num_bids is None
    assert item.item_id == "ebay-987"


def test_normalize_rejects_incomplete():
    assert EbayClient._normalize({"title": "no url or id"}) is None
    assert EbayClient._normalize({"itemId": "1", "itemWebUrl": "u"}) is None  # no title


def test_fetch_items_no_token_returns_empty(monkeypatch):
    client = EbayClient("id", "secret", ["bangle"])
    monkeypatch.setattr(client, "_get_token", lambda: None)
    assert client.fetch_items() == []
