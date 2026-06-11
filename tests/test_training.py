"""Tests for the labeling / training API and the few-shot store."""

import os
import tempfile

from fastapi.testclient import TestClient

from goldscanner.config import Config
from goldscanner.models import Item
from goldscanner.service import Service
from goldscanner.web import create_app


def make_client():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    cfg = Config(queries=["bangle"], use_ai=False, email_enabled=False, db_path=path)
    service = Service(cfg)
    return service, TestClient(create_app(service)), path


def seed_match(service, item_id="1", img="https://example.com/a.jpg"):
    service.store.record(
        Item(item_id=item_id, title="Gold filled enamel bangle", image_urls=[img]),
        matched=True,
        confidence=0.9,
        reasoning="ok",
    )


def test_add_list_delete_example():
    service, client, path = make_client()
    try:
        r = client.post(
            "/api/examples",
            json={"image_url": "https://x/y.jpg", "label": "positive"},
        )
        assert r.status_code == 200
        ex_id = r.json()["example"]["id"]
        assert r.json()["counts"]["positive"] == 1

        listed = client.get("/api/examples?label=positive").json()
        assert len(listed["examples"]) == 1

        assert client.post(
            "/api/examples", json={"image_url": "https://x/y.jpg", "label": "bogus"}
        ).status_code == 400

        d = client.delete(f"/api/examples/{ex_id}")
        assert d.status_code == 200
        assert d.json()["counts"]["positive"] == 0
    finally:
        service.store.close()
        os.remove(path)


def test_favorite_seeds_positive_hide_seeds_negative():
    service, client, path = make_client()
    try:
        seed_match(service, "1", "https://example.com/fav.jpg")
        seed_match(service, "2", "https://example.com/hide.jpg")

        client.post("/api/items/1/status", json={"status": "favorite"})
        client.post("/api/items/2/status", json={"status": "dismissed"})

        counts = client.get("/api/examples").json()["counts"]
        assert counts["positive"] == 1
        assert counts["negative"] == 1
    finally:
        service.store.close()
        os.remove(path)


def test_guidance_roundtrip():
    service, client, path = make_client()
    try:
        assert client.get("/api/guidance").json()["text"] == ""
        client.put("/api/guidance", json={"text": "prefer vintage cloisonné"})
        assert client.get("/api/guidance").json()["text"] == "prefer vintage cloisonné"
        # surfaced in status too
        assert client.get("/api/status").json()["guidance"] == "prefer vintage cloisonné"
    finally:
        service.store.close()
        os.remove(path)


def test_labeling_queue_excludes_labeled():
    service, client, path = make_client()
    try:
        seed_match(service, "1", "https://example.com/q.jpg")
        assert len(client.get("/api/queue").json()["items"]) == 1
        # Label it -> drops out of the queue
        client.post(
            "/api/examples",
            json={"image_url": "https://example.com/q.jpg", "label": "positive"},
        )
        assert client.get("/api/queue").json()["items"] == []
    finally:
        service.store.close()
        os.remove(path)
