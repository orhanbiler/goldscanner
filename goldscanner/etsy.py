"""Etsy listings source.

Two modes:
  * **API mode** (preferred) — when an `ETSY_API_KEY` is provided, we call Etsy's
    official Open API v3 (`/v3/application/listings/active`). Reliable JSON, not
    bot-blocked. Get a key at https://www.etsy.com/developers (create an app).
  * **Scrape fallback** — without a key, we fetch search/market page HTML and
    parse the embedded JSON-LD. Etsy uses bot protection (DataDome), so this is
    frequently blocked from datacenter IPs (e.g. Railway) and may return nothing.

Both modes degrade gracefully: any failure logs a warning and returns [].
"""

from __future__ import annotations

import json
import logging
import re

import requests

from .models import Item

log = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

_LDJSON_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.S | re.I,
)
_LISTING_ID_RE = re.compile(r"/listing/(\d+)")

ETSY_API_URL = "https://openapi.etsy.com/v3/application/listings/active"


class EtsyClient:
    def __init__(
        self,
        urls: list[str] | None = None,
        api_key: str = "",
        queries: list[str] | None = None,
        limit: int = 50,
        timeout: int = 30,
    ):
        self.urls = urls or []
        self.api_key = api_key
        self.queries = queries or []
        self.limit = max(1, min(limit, 100))
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": _UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )

    def fetch_items(self) -> list[Item]:
        """Uniform entry point used by the scanner."""
        if self.api_key:
            return self._fetch_via_api()
        items: list[Item] = []
        seen: set[str] = set()
        for url in self.urls:
            for item in self.fetch_listings(url):
                if item.item_id not in seen:
                    seen.add(item.item_id)
                    items.append(item)
        return items

    # -- API mode ------------------------------------------------------------

    def _fetch_via_api(self) -> list[Item]:
        items: list[Item] = []
        seen: set[str] = set()
        for query in self.queries:
            try:
                resp = self.session.get(
                    ETSY_API_URL,
                    headers={"x-api-key": self.api_key},
                    params={
                        "keywords": query,
                        "limit": self.limit,
                        "includes": "Images",
                    },
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:  # noqa: BLE001
                log.warning("etsy api search failed (q=%r): %s", query, exc)
                continue
            for raw in data.get("results") or []:
                item = self._normalize_api(raw)
                if item and item.item_id not in seen:
                    seen.add(item.item_id)
                    items.append(item)
        return items

    @staticmethod
    def _normalize_api(raw: dict) -> Item | None:
        listing_id = raw.get("listing_id")
        title = str(raw.get("title") or "").strip()
        if not listing_id or not title:
            return None
        url = str(raw.get("url") or f"https://www.etsy.com/listing/{listing_id}")

        price = raw.get("price") or {}
        amount, divisor = price.get("amount"), price.get("divisor")
        price_str = None
        if isinstance(amount, (int, float)) and divisor:
            price_str = f"{amount / divisor:.2f}"

        image_url = None
        images = raw.get("images") or []
        if images and isinstance(images[0], dict):
            image_url = (
                images[0].get("url_fullxfull")
                or images[0].get("url_570xN")
                or images[0].get("url_170x135")
            )

        return Item(
            item_id=f"etsy-{listing_id}",
            title=title,
            source="etsy",
            current_price=price_str,
            end_time=None,
            num_bids=None,
            image_urls=[image_url] if image_url else [],
            url=url.split("?")[0],
        )

    # -- scrape fallback -----------------------------------------------------

    def fetch_listings(self, url: str) -> list[Item]:
        """Fetch one Etsy search/market page and return its listings.

        Best-effort: any failure (block, network, layout change) returns [].
        """
        try:
            resp = self.session.get(url, timeout=self.timeout)
        except Exception as exc:  # noqa: BLE001
            log.warning("etsy fetch failed (%s): %s", url, exc)
            return []
        if resp.status_code != 200:
            log.warning(
                "etsy returned HTTP %s for %s (likely bot protection)",
                resp.status_code,
                url,
            )
            return []
        items = self.parse_listings(resp.text)
        if not items:
            log.warning(
                "etsy page had no parseable listings (%s) — blocked or layout change?",
                url,
            )
        return items

    # -- parsing (pure, unit-testable) ---------------------------------------

    @classmethod
    def parse_listings(cls, html: str) -> list[Item]:
        items: list[Item] = []
        seen_ids: set[str] = set()
        for raw in _LDJSON_RE.findall(html):
            try:
                data = json.loads(raw.strip())
            except json.JSONDecodeError:
                continue
            for product in cls._iter_products(data):
                item = cls._normalize(product)
                if item and item.item_id not in seen_ids:
                    seen_ids.add(item.item_id)
                    items.append(item)
        return items

    @staticmethod
    def _iter_products(data):
        """Yield Product dicts from JSON-LD, tolerating shape variations."""
        nodes = data if isinstance(data, list) else [data]
        for node in nodes:
            if not isinstance(node, dict):
                continue
            if node.get("@type") == "Product":
                yield node
            for element in node.get("itemListElement") or []:
                if not isinstance(element, dict):
                    continue
                product = element.get("item", element)
                if isinstance(product, dict) and product.get("@type") == "Product":
                    yield product

    @classmethod
    def _normalize(cls, product: dict) -> Item | None:
        url = str(product.get("url") or "")
        if url.startswith("//"):
            url = "https:" + url
        title = str(product.get("name") or "").strip()
        if not url or not title:
            return None

        match = _LISTING_ID_RE.search(url)
        listing_id = match.group(1) if match else str(abs(hash(url)))
        # Strip tracking params for a clean, stable link.
        clean_url = url.split("?")[0]

        image = product.get("image")
        if isinstance(image, list):
            image = image[0] if image else None
        if isinstance(image, dict):
            image = image.get("contentUrl") or image.get("url")
        image_url = str(image) if image else None
        if image_url and image_url.startswith("//"):
            image_url = "https:" + image_url

        return Item(
            item_id=f"etsy-{listing_id}",
            title=title,
            source="etsy",
            current_price=cls._price(product.get("offers")),
            end_time=None,  # fixed-price listings
            num_bids=None,
            image_urls=[image_url] if image_url else [],
            url=clean_url,
        )

    @staticmethod
    def _price(offers) -> str | None:
        if isinstance(offers, list):
            offers = offers[0] if offers else None
        if not isinstance(offers, dict):
            return None
        for key in ("price", "lowPrice", "highPrice"):
            value = offers.get(key)
            if value is not None and str(value).strip() != "":
                return str(value)
        return None
