"""FastAPI web app: serves the React UI and the JSON API."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import Config
from .service import Service
from .store import (
    LABEL_NEGATIVE,
    LABEL_POSITIVE,
    SETTING_GUIDANCE,
    STATUS_DISMISSED,
    STATUS_FAVORITE,
    VALID_LABELS,
    VALID_STATUSES,
)

log = logging.getLogger(__name__)

_FALLBACK_HTML = """<!doctype html><html><head><meta charset="utf-8">
<title>goldscanner</title></head><body style="font-family:system-ui;padding:40px">
<h1>goldscanner</h1><p>The web UI hasn't been built yet. Run
<code>cd frontend &amp;&amp; npm install &amp;&amp; npm run build</code>, or use the
Docker image which builds it for you. The JSON API is live at <code>/api/status</code>.</p>
</body></html>"""


def _find_dist() -> Path | None:
    candidates = []
    env = os.environ.get("GOLDSCANNER_WEB_DIST")
    if env:
        candidates.append(Path(env))
    here = Path(__file__).parent
    candidates.append(here / "web_dist")          # baked into the image
    candidates.append(here.parent / "frontend" / "dist")  # local `npm run build`
    for c in candidates:
        if (c / "index.html").exists():
            return c
    return None


class StatusUpdate(BaseModel):
    status: str


class ExampleCreate(BaseModel):
    image_url: str
    label: str
    item_id: str | None = None
    title: str | None = None
    note: str | None = None


class GuidanceUpdate(BaseModel):
    text: str


def create_app(service: Service) -> FastAPI:
    app = FastAPI(title="goldscanner", docs_url=None, redoc_url=None)
    dist = _find_dist()

    # -- API ---------------------------------------------------------------

    @app.get("/healthz")
    def healthz() -> dict:
        return {"ok": True}

    @app.get("/api/status")
    def api_status() -> dict:
        data = service.status()
        data["examples"] = service.store.example_counts()
        data["guidance"] = service.store.get_setting(SETTING_GUIDANCE, "")
        data["target_description"] = service.config.target_description
        return data

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
        # Auto-seed training labels from the user's favorite / hide actions.
        item = service.store.get_item(item_id)
        if item and item.get("image_url"):
            if body.status == STATUS_FAVORITE:
                service.store.add_example(
                    item["image_url"], LABEL_POSITIVE, item_id, item.get("title")
                )
            elif body.status == STATUS_DISMISSED:
                service.store.add_example(
                    item["image_url"], LABEL_NEGATIVE, item_id, item.get("title")
                )
        return {"ok": True, "counts": service.store.counts()}

    @app.post("/api/scan")
    def api_scan() -> JSONResponse:
        if service.scanning:
            return JSONResponse({"ok": False, "reason": "already scanning"}, status_code=409)
        matches = service.scan_once()
        return JSONResponse({"ok": True, "matches": matches})

    # -- training / labeling ----------------------------------------------

    @app.get("/api/queue")
    def api_queue(limit: int = 40) -> dict:
        return {"items": service.store.labeling_queue(limit=max(1, min(limit, 100)))}

    @app.get("/api/examples")
    def api_examples(label: str | None = None) -> dict:
        if label is not None and label not in VALID_LABELS:
            raise HTTPException(400, "invalid label")
        return {
            "examples": service.store.list_examples(label),
            "counts": service.store.example_counts(),
        }

    @app.post("/api/examples")
    def api_add_example(body: ExampleCreate) -> dict:
        if body.label not in VALID_LABELS:
            raise HTTPException(400, "invalid label")
        ex = service.store.add_example(
            image_url=body.image_url,
            label=body.label,
            item_id=body.item_id,
            title=body.title,
            note=body.note,
        )
        if ex is None:
            raise HTTPException(400, "could not add example")
        return {"ok": True, "example": ex, "counts": service.store.example_counts()}

    @app.delete("/api/examples/{example_id}")
    def api_delete_example(example_id: int) -> dict:
        ok = service.store.delete_example(example_id)
        if not ok:
            raise HTTPException(404, "example not found")
        return {"ok": True, "counts": service.store.example_counts()}

    @app.get("/api/guidance")
    def api_get_guidance() -> dict:
        return {"text": service.store.get_setting(SETTING_GUIDANCE, "")}

    @app.put("/api/guidance")
    def api_set_guidance(body: GuidanceUpdate) -> dict:
        service.store.set_setting(SETTING_GUIDANCE, body.text)
        return {"ok": True, "text": body.text}

    # -- static (React build) ----------------------------------------------

    if dist is not None:
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/")
        def index() -> FileResponse:
            return FileResponse(dist / "index.html")

        @app.get("/{full_path:path}")
        def spa(full_path: str):
            if full_path.startswith("api/"):
                raise HTTPException(404, "not found")
            candidate = dist / full_path
            if full_path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")
    else:

        @app.get("/")
        def index_fallback() -> HTMLResponse:
            return HTMLResponse(_FALLBACK_HTML)

    return app


def build_app() -> FastAPI:
    service = Service(Config.from_env())
    service.start_background()
    return create_app(service)
