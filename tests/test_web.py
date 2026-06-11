"""Web API tests using a Service with a fake scanner (no network/API key)."""

import os
import tempfile

from fastapi.testclient import TestClient

from goldscanner.config import Config
from goldscanner.models import Item
from goldscanner.service import Service
from goldscanner.web import create_app


def make_service():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    cfg = Config(
        queries=["bangle"],
        title_keywords=["bangle"],
        use_ai=False,
        email_enabled=False,
        seed_defaults=False,
        db_path=path,
    )
    service = Service(cfg)
    return service, path


def seed_match(service, item_id="1", title="Gold filled enamel bangle"):
    item = Item(
        item_id=item_id,
        title=title,
        current_price="19.99",
        end_time="2026-06-12",
        num_bids=2,
        image_urls=["https://example.com/x.jpg"],
    )
    service.store.record(item, matched=True, confidence=0.9, reasoning="looks right")


def test_health_and_status():
    service, path = make_service()
    try:
        client = TestClient(create_app(service))
        assert client.get("/healthz").json() == {"ok": True}
        body = client.get("/api/status").json()
        assert "counts" in body and body["counts"]["matched"] == 0
    finally:
        service.store.close()
        os.remove(path)


def test_items_and_favorite_flow():
    service, path = make_service()
    try:
        seed_match(service)
        client = TestClient(create_app(service))

        # Shows under "new"
        new_items = client.get("/api/items?status=new").json()["items"]
        assert [i["item_id"] for i in new_items] == ["1"]

        # Favorite it
        r = client.post("/api/items/1/status", json={"status": "favorite"})
        assert r.status_code == 200
        assert r.json()["counts"]["favorite"] == 1

        # Now appears under favorites, not under new
        assert client.get("/api/items?status=favorite").json()["items"][0]["item_id"] == "1"
        assert client.get("/api/items?status=new").json()["items"] == []

        # Bad status rejected; unknown item 404s
        assert client.post("/api/items/1/status", json={"status": "nope"}).status_code == 400
        assert client.post("/api/items/999/status", json={"status": "favorite"}).status_code == 404
    finally:
        service.store.close()
        os.remove(path)


def test_index_served():
    service, path = make_service()
    try:
        client = TestClient(create_app(service))
        r = client.get("/")
        assert r.status_code == 200
        assert "goldscanner" in r.text
    finally:
        service.store.close()
        os.remove(path)
