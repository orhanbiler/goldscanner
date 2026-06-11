"""Client for shopgoodwill.com's (unofficial) JSON API.

shopgoodwill has no official API. The site's frontend talks to a JSON backend at
buyerapi.shopgoodwill.com. Searching is public (no login required); we only read.
"""

from __future__ import annotations

import logging

import requests

from .models import Item

log = logging.getLogger(__name__)

API_BASE = "https://buyerapi.shopgoodwill.com/api"
SEARCH_URL = f"{API_BASE}/Search/ItemListing"
ITEM_DETAIL_URL = f"{API_BASE}/ItemDetail/GetItemDetailModelByItemId"
# Listing thumbnails / detail photos are served from this CDN.
IMAGE_BASE = "https://shopgoodwillimages.azureedge.net/production/"

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def sniff_media_type(data: bytes, fallback: str = "image/jpeg") -> str:
    """Detect the actual image type from magic bytes.

    CDNs sometimes serve a PNG with a Content-Type of image/jpeg; the Anthropic
    API rejects mismatched media types, so trust the bytes over the header.
    """
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return fallback


def _abs_image(raw: str | None) -> str | None:
    if not raw:
        return None
    raw = str(raw).strip()
    if not raw:
        return None
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    return IMAGE_BASE + raw.lstrip("/")


class ShopGoodwillClient:
    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": _UA,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Origin": "https://shopgoodwill.com",
                "Referer": "https://shopgoodwill.com/",
            }
        )

    def search(self, query: str, page: int = 1, page_size: int = 40) -> list[Item]:
        """Search listings for `query`. Returns normalized Items."""
        payload = self._search_payload(query, page, page_size)
        resp = self.session.post(SEARCH_URL, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        raw_items = (data.get("searchResults") or {}).get("items") or []
        return [self._normalize(raw) for raw in raw_items]

    def fetch_detail_images(self, item_id: str, limit: int = 5) -> list[str]:
        """Fetch additional photo URLs for an item from its detail page.

        Best-effort: returns [] on any failure rather than raising, so a single
        bad item never breaks a scan.
        """
        try:
            resp = self.session.get(
                f"{ITEM_DETAIL_URL}/{item_id}", timeout=self.timeout
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001 - best effort
            log.debug("detail fetch failed for %s: %s", item_id, exc)
            return []

        urls: list[str] = []
        for key in ("imageUrlString", "imageUrl"):
            primary = _abs_image(data.get(key))
            if primary:
                urls.append(primary)
        for img in data.get("imageUrlList") or data.get("images") or []:
            candidate = img if isinstance(img, str) else (
                img.get("imageUrl") if isinstance(img, dict) else None
            )
            abs_url = _abs_image(candidate)
            if abs_url and abs_url not in urls:
                urls.append(abs_url)
        return urls[:limit]

    def download_image(self, url: str) -> tuple[bytes, str] | None:
        """Download an image. Returns (bytes, media_type) or None on failure."""
        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001 - best effort
            log.debug("image download failed %s: %s", url, exc)
            return None
        header_type = resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
        if not header_type.startswith("image/"):
            header_type = "image/jpeg"
        # Trust magic bytes over the header — CDNs lie about content types.
        media_type = sniff_media_type(resp.content, fallback=header_type)
        return resp.content, media_type

    # -- internals -----------------------------------------------------------

    @staticmethod
    def _normalize(raw: dict) -> Item:
        item_id = str(raw.get("itemId") or raw.get("ItemId") or "")
        image = _abs_image(raw.get("imageUrl") or raw.get("imageURL"))
        num_bids = raw.get("numBids", raw.get("numberOfBids"))
        try:
            num_bids = int(num_bids) if num_bids is not None else None
        except (TypeError, ValueError):
            num_bids = None
        return Item(
            item_id=item_id,
            title=str(raw.get("title") or "").strip(),
            source="shopgoodwill",
            current_price=(
                str(raw.get("currentPrice")) if raw.get("currentPrice") is not None else None
            ),
            end_time=raw.get("endTime"),
            num_bids=num_bids,
            image_urls=[image] if image else [],
            url=f"https://shopgoodwill.com/item/{item_id}",
        )

    @staticmethod
    def _search_payload(query: str, page: int, page_size: int) -> dict:
        return {
            "isSize": False,
            "isWeddingCatagory": False,
            "isMultipleCategoryIds": False,
            "isFromHeaderMenuTab": False,
            "layout": "",
            "searchText": query,
            "selectedGroup": "",
            "selectedCategoryIds": "",
            "selectedSellerIds": "",
            "lowPrice": "0",
            "highPrice": "999999",
            "searchBuyNowOnly": "",
            "searchPickupOnly": False,
            "searchNoPickupOnly": False,
            "searchDescriptions": False,
            "searchClosedAuctions": False,
            "closedAuctionEndingDate": "",
            "closedAuctionDaysBack": "",
            "searchCanceledItems": False,
            "searchUSOnlyFlag": False,
            "categoryId": 0,
            "categoryLevelNo": "1",
            "categoryLevel": 1,
            "categoryColumn": "",
            "partNumber": "",
            "savedSearchId": 0,
            "useBuyerPrefs": True,
            "sortColumn": "1",
            "page": page,
            "pageSize": page_size,
            "sortDescending": True,
        }
