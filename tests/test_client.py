from goldscanner.client import ShopGoodwillClient, _abs_image


def test_abs_image_relative():
    assert _abs_image("foo/bar.jpg") == (
        "https://shopgoodwillimages.azureedge.net/production/foo/bar.jpg"
    )


def test_abs_image_absolute_passthrough():
    url = "https://example.com/x.jpg"
    assert _abs_image(url) == url


def test_abs_image_empty():
    assert _abs_image("") is None
    assert _abs_image(None) is None


def test_normalize_extracts_fields():
    raw = {
        "itemId": 12345,
        "title": "  Gold filled enamel bangle  ",
        "currentPrice": 19.99,
        "endTime": "2026-06-12T00:00:00",
        "numBids": "3",
        "imageUrl": "prod/abc.jpg",
    }
    item = ShopGoodwillClient._normalize(raw)
    assert item.item_id == "12345"
    assert item.title == "Gold filled enamel bangle"
    assert item.current_price == "19.99"
    assert item.num_bids == 3
    assert item.image_urls == [
        "https://shopgoodwillimages.azureedge.net/production/prod/abc.jpg"
    ]
    assert item.url == "https://shopgoodwill.com/item/12345"
