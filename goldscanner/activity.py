"""A small in-memory, thread-safe activity feed for the live debug view.

The background scanner and request threads both write to it; the web layer
reads recent entries for the UI. It's intentionally ephemeral (a ring buffer) —
a running narrative of what the app is doing right now, not durable history.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque

log = logging.getLogger(__name__)

# Levels map to colors/icons in the UI.
INFO = "info"
SUCCESS = "success"
WARN = "warn"
MUTED = "muted"


class ActivityLog:
    def __init__(self, maxlen: int = 500):
        self._events: deque[dict] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._seq = 0

    def add(self, message: str, level: str = INFO) -> None:
        with self._lock:
            self._seq += 1
            self._events.append(
                {"id": self._seq, "ts": time.time(), "level": level, "message": message}
            )
        # Mirror to standard logs too, so Railway logs tell the same story.
        log.info("%s", message)

    def since(self, after: int = 0, limit: int = 300) -> dict:
        with self._lock:
            events = [e for e in self._events if e["id"] > after][-limit:]
            last_id = self._seq
        return {"events": events, "last_id": last_id}
