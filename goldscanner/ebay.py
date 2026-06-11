"""eBay listings source via the official Browse API.

Uses OAuth client-credentials (application token) to call
`/buy/browse/v1/item_summary/search`. This is the reliable, non-bot-blocked
path — unlike scraping ebay.com — and returns clean JSON with images, price,
and a direct item URL.

Get free credentials at https://developer.ebay.com (create an app → use the
**Production** App ID as EBAY_CLIENT_ID and Cert ID as EBAY_CLIENT_SECRET).

Best-effort: any auth/network/shape failure logs a warning and returns [],
so a hiccup never breaks the scan.
"""

from __future__ import annotations

import base64
import logging
import time

import requests

from .models import Item

log = logging.getLogger(__name__)

OAUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"
SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
SCOPE = "https://api.ebay.com/oauth/api_scope"


class EbayClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        queries: list[str],
        limit: int = 50,
        marketplace: str = "EBAY_US",
        timeout: int = 30,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.queries = queries
        self.limit = max(1, min(limit, 200))
        self.marketplace = marketplace
        self.timeout = timeout
        self.session = requests.Session()
        self._token: str | None = None
        self._token_expiry: float = 0.0

    def fetch_items(self) -> list[Item]:
        token = self._get_token()
        if not token:
            return []
        items: list[Item] = []
        seen: set[str] = set()
        for query in self.queries:
            for raw in self._search(query, token):
                item = self._normalize(raw)
                if item and item.item_id not in seen:
                    seen.add(item.item_id)
                    items.append(item)
        return items

    # -- internals -----------------------------------------------------------

    def _get_token(self) -> str | None:
        if self._token and time.time() < self._token_expiry - 60:
            return self._token
        creds = base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()
        try:
            resp = self.session.post(
                OAUTH_URL,
                headers={
                    "Authorization": f"Basic {creds}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={"grant_type": "client_credentials", "scope": SCOPE},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            log.warning("ebay oauth failed (check EBAY_CLIENT_ID/SECRET): %s", exc)
            return None
        self._token = data.get("access_token")
        self._token_expiry = time.time() + float(data.get("expires_in", 7200))
        return self._token

    def _search(self, query: str, token: str) -> list[dict]:
        try:
            resp = self.session.get(
                SEARCH_URL,
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-EBAY-C-MARKETPLACE-ID": self.marketplace,
                },
                params={"q": query, "limit": self.limit},
                timeout=self.timeout,
            )
            if resp.status_code == 401:
                # Token went stale; drop it so the next cycle re-auths.
                self._token = None
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            log.warning("ebay search failed (q=%r): %s", query, exc)
            return []
        return data.get("itemSummaries") or []

    @staticmethod
    def _normalize(raw: dict) -> Item | None:
        item_id = str(raw.get("itemId") or "")
        title = str(raw.get("title") or "").strip()
        url = str(raw.get("itemWebUrl") or "")
        if not item_id or not title or not url:
            return None

        image = (raw.get("image") or {}).get("imageUrl")
        if not image:
            thumbs = raw.get("thumbnailImages") or []
            if thumbs:
                image = thumbs[0].get("imageUrl")

        price = raw.get("price") or {}
        price_value = price.get("value")

        bids = raw.get("bidCount")
        try:
            bids = int(bids) if bids is not None else None
        except (TypeError, ValueError):
            bids = None

        # Stable, source-prefixed id (eBay ids look like "v1|123|0").
        clean_id = item_id.split("|")[1] if "|" in item_id else item_id
        return Item(
            item_id=f"ebay-{clean_id}",
            title=title,
            source="ebay",
            current_price=str(price_value) if price_value is not None else None,
            end_time=raw.get("itemEndDate"),
            num_bids=bids,
            image_urls=[str(image)] if image else [],
            url=url,
        )
