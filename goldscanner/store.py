"""SQLite store of items the scanner has processed.

Holds two responsibilities:
  * dedupe — every item we examine gets a row, so we never re-score it
  * the matched candidates the web UI shows (with a user-settable status:
    new / favorite / dismissed)

Thread-safe: the background scanner thread and the web request threads share one
connection guarded by a lock (low volume, so a single lock is plenty).
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time

# Valid user-facing statuses for matched items.
STATUS_NEW = "new"
STATUS_FAVORITE = "favorite"
STATUS_DISMISSED = "dismissed"
VALID_STATUSES = {STATUS_NEW, STATUS_FAVORITE, STATUS_DISMISSED}


class SeenStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        parent = os.path.dirname(os.path.abspath(db_path))
        os.makedirs(parent, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._migrate()

    def _migrate(self) -> None:
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS items (
                    item_id     TEXT PRIMARY KEY,
                    title       TEXT,
                    price       TEXT,
                    end_time    TEXT,
                    num_bids    INTEGER,
                    image_url   TEXT,
                    url         TEXT,
                    matched     INTEGER NOT NULL DEFAULT 0,
                    confidence  REAL,
                    reasoning   TEXT,
                    status      TEXT NOT NULL DEFAULT 'new',
                    first_seen  REAL NOT NULL,
                    updated     REAL NOT NULL
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_items_matched_status "
                "ON items (matched, status)"
            )
            self._conn.commit()

    # -- dedupe --------------------------------------------------------------

    def is_seen(self, item_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "SELECT 1 FROM items WHERE item_id = ?", (str(item_id),)
            )
            return cur.fetchone() is not None

    def record(self, item, matched: bool, confidence: float | None, reasoning: str) -> None:
        """Insert (or ignore if already present) a processed item."""
        now = time.time()
        with self._lock:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO items
                    (item_id, title, price, end_time, num_bids, image_url, url,
                     matched, confidence, reasoning, status, first_seen, updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(item.item_id),
                    item.title,
                    item.current_price,
                    item.end_time,
                    item.num_bids,
                    item.image_urls[0] if item.image_urls else None,
                    item.url,
                    1 if matched else 0,
                    confidence,
                    reasoning,
                    STATUS_NEW,
                    now,
                    now,
                ),
            )
            self._conn.commit()

    # -- web queries ---------------------------------------------------------

    def list_matches(self, status: str | None = None) -> list[dict]:
        """Matched items, optionally filtered by status, newest first."""
        query = "SELECT * FROM items WHERE matched = 1"
        params: list = []
        if status and status != "all":
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY first_seen DESC"
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def set_status(self, item_id: str, status: str) -> bool:
        if status not in VALID_STATUSES:
            return False
        with self._lock:
            cur = self._conn.execute(
                "UPDATE items SET status = ?, updated = ? WHERE item_id = ? AND matched = 1",
                (status, time.time(), str(item_id)),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def counts(self) -> dict:
        with self._lock:
            total_seen = self._conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
            rows = self._conn.execute(
                "SELECT status, COUNT(*) AS n FROM items WHERE matched = 1 GROUP BY status"
            ).fetchall()
        by_status = {r["status"]: r["n"] for r in rows}
        matched_total = sum(by_status.values())
        return {
            "seen": int(total_seen),
            "matched": int(matched_total),
            "new": int(by_status.get(STATUS_NEW, 0)),
            "favorite": int(by_status.get(STATUS_FAVORITE, 0)),
            "dismissed": int(by_status.get(STATUS_DISMISSED, 0)),
        }

    def count(self) -> int:
        return self.counts()["seen"]

    def close(self) -> None:
        with self._lock:
            self._conn.close()
