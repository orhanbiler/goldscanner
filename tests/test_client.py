from goldscanner.client import ShopGoodwillClient, _abs_image, sniff_media_type


def test_sniff_media_type_detects_real_format():
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 16
    gif = b"GIF89a" + b"\x00" * 16
    webp = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 8
    assert sniff_media_type(png, "image/jpeg") == "image/png"  # header lied
    assert sniff_media_type(jpeg, "image/png") == "image/jpeg"
    assert sniff_media_type(gif) == "image/gif"
    assert sniff_media_type(webp) == "image/webp"
    assert sniff_media_type(b"unknown blob", "image/jpeg") == "image/jpeg"


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
