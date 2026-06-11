"""FastAPI web app: serves the mobile-friendly UI and a small JSON API."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from .config import Config
from .service import Service
from .store import VALID_STATUSES

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


class StatusUpdate(BaseModel):
    status: str


def create_app(service: Service) -> FastAPI:
    app = FastAPI(title="goldscanner", docs_url=None, redoc_url=None)

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True}

    @app.get("/api/status")
    def api_status() -> dict:
        return service.status()

    @app.get("/api/items")
    def api_items(status: str = "new") -> dict:
        if status not in VALID_STATUSES and status != "all":
            raise HTTPException(400, "invalid status filter")
        items = service.store.list_matches(None if status == "all" else status)
        return {"items": items, "counts": service.store.counts()}

    @app.post("/api/items/{item_id}/status")
    def api_set_status(item_id: str, body: StatusUpdate) -> dict:
        if body.status not in VALID_STATUSES:
            raise HTTPException(400, "invalid status")
        ok = service.store.set_status(item_id, body.status)
        if not ok:
            raise HTTPException(404, "item not found")
        return {"ok": True, "counts": service.store.counts()}

    @app.post("/api/scan")
    def api_scan() -> JSONResponse:
        if service.scanning:
            return JSONResponse({"ok": False, "reason": "already scanning"}, status_code=409)
        matches = service.scan_once()
        return JSONResponse({"ok": True, "matches": matches})

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app


def build_app() -> FastAPI:
    """Used by `uvicorn goldscanner.web:build_app` style factory if desired."""
    service = Service(Config.from_env())
    service.start_background()
    return create_app(service)
