"""SQLite store of items we've already processed, so each item is handled once."""

from __future__ import annotations

import os
import sqlite3
import time


class SeenStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        parent = os.path.dirname(os.path.abspath(db_path))
        os.makedirs(parent, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS seen_items (
                item_id     TEXT PRIMARY KEY,
                title       TEXT,
                matched     INTEGER NOT NULL DEFAULT 0,
                confidence  REAL,
                first_seen  REAL NOT NULL
            )
            """
        )
        self._conn.commit()

    def is_seen(self, item_id: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM seen_items WHERE item_id = ?", (str(item_id),)
        )
        return cur.fetchone() is not None

    def mark_seen(
        self,
        item_id: str,
        title: str = "",
        matched: bool = False,
        confidence: float | None = None,
    ) -> None:
        self._conn.execute(
            """
            INSERT OR IGNORE INTO seen_items
                (item_id, title, matched, confidence, first_seen)
            VALUES (?, ?, ?, ?, ?)
            """,
            (str(item_id), title, 1 if matched else 0, confidence, time.time()),
        )
        self._conn.commit()

    def count(self) -> int:
        cur = self._conn.execute("SELECT COUNT(*) FROM seen_items")
        return int(cur.fetchone()[0])

    def close(self) -> None:
        self._conn.close()
