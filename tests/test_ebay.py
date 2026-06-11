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

    def fail_token():
        client.last_error = "oauth failed"
        return None

    monkeypatch.setattr(client, "_get_token", fail_token)
    assert client.fetch_items() == []
    assert client.last_error == "oauth failed"


def test_etsy_api_mode_two_step_fetch(monkeypatch):
    """API mode: search for ids, then batch-fetch with images."""
    from goldscanner.etsy import EtsyClient

    calls = []

    class FakeResp:
        status_code = 200

        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self.payload

    def fake_get(url, headers=None, params=None, timeout=None):
        calls.append((url, params))
        if "listings/active" in url:
            return FakeResp({"results": [{"listing_id": 111}, {"listing_id": 222}]})
        if "listings/batch" in url:
            assert params["listing_ids"] == "111,222"
            assert params["includes"] == "Images"
            return FakeResp(
                {
                    "results": [
                        {
                            "listing_id": 111,
                            "title": "Victorian gold bangle",
                            "url": "https://www.etsy.com/listing/111/x?ref=z",
                            "price": {"amount": 24500, "divisor": 100},
                            "images": [{"url_fullxfull": "https://i.etsystatic.com/1.jpg"}],
                        },
                        {
                            "listing_id": 222,
                            "title": "Enamel bangle",
                            "url": "https://www.etsy.com/listing/222/y",
                            "price": {"amount": 9900, "divisor": 100},
                            "images": [{"url_570xN": "https://i.etsystatic.com/2.jpg"}],
                        },
                    ]
                }
            )
        raise AssertionError(f"unexpected url {url}")

    client = EtsyClient(api_key="k", queries=["victorian bangle"])
    monkeypatch.setattr(client.session, "get", fake_get)

    items = client.fetch_items()
    assert [i.item_id for i in items] == ["etsy-111", "etsy-222"]
    assert items[0].current_price == "245.00"
    assert items[0].image_urls == ["https://i.etsystatic.com/1.jpg"]
    assert items[0].url == "https://www.etsy.com/listing/111/x"
    assert items[1].image_urls == ["https://i.etsystatic.com/2.jpg"]
    assert client.last_error is None
