"""SQLite store: seen items / matches, training examples, and settings.

Responsibilities:
  * dedupe — every item we examine gets a row, so we never re-score it
  * matched candidates the web UI shows (status: new / favorite / dismissed)
  * training examples — user-labeled photos used as few-shot references
  * settings — small key/value bag (e.g. the editable guidance text)

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

# Valid training labels.
LABEL_POSITIVE = "positive"
LABEL_NEGATIVE = "negative"
VALID_LABELS = {LABEL_POSITIVE, LABEL_NEGATIVE}

SETTING_GUIDANCE = "guidance"


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
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS items (
                    item_id     TEXT PRIMARY KEY,
                    source      TEXT NOT NULL DEFAULT 'shopgoodwill',
                    title       TEXT,
                    price       TEXT,
                    end_time    TEXT,
                    num_bids    INTEGER,
                    image_url   TEXT,
                    url         TEXT,
                    matched     INTEGER NOT NULL DEFAULT 0,
                    confidence  REAL,
                    reasoning   TEXT,
                    gold_type   TEXT,
                    karat       TEXT,
                    hallmark    TEXT,
                    antique_style TEXT,
                    status      TEXT NOT NULL DEFAULT 'new',
                    first_seen  REAL NOT NULL,
                    updated     REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_items_matched_status
                    ON items (matched, status);

                CREATE TABLE IF NOT EXISTS examples (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id    TEXT,
                    title      TEXT,
                    image_url  TEXT NOT NULL,
                    label      TEXT NOT NULL,
                    note       TEXT,
                    created    REAL NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_examples_image
                    ON examples (image_url);

                CREATE TABLE IF NOT EXISTS settings (
                    key   TEXT PRIMARY KEY,
                    value TEXT
                );
                """
            )
            # Migrations for databases created by earlier versions.
            cols = [r[1] for r in self._conn.execute("PRAGMA table_info(items)")]
            if "source" not in cols:
                self._conn.execute(
                    "ALTER TABLE items ADD COLUMN source TEXT NOT NULL "
                    "DEFAULT 'shopgoodwill'"
                )
            for col in ("gold_type", "karat", "hallmark", "antique_style"):
                if col not in cols:
                    self._conn.execute(f"ALTER TABLE items ADD COLUMN {col} TEXT")
            self._conn.commit()

    # -- dedupe / items ------------------------------------------------------

    def is_seen(self, item_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "SELECT 1 FROM items WHERE item_id = ?", (str(item_id),)
            )
            return cur.fetchone() is not None

    def record(
        self,
        item,
        matched: bool,
        confidence: float | None,
        reasoning: str,
        gold_type: str | None = None,
        karat: str | None = None,
        hallmark: str | None = None,
        antique_style: str | None = None,
    ) -> None:
        now = time.time()
        with self._lock:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO items
                    (item_id, source, title, price, end_time, num_bids, image_url, url,
                     matched, confidence, reasoning, gold_type, karat, hallmark,
                     antique_style, status, first_seen, updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(item.item_id),
                    item.source,
                    item.title,
                    item.current_price,
                    item.end_time,
                    item.num_bids,
                    item.image_urls[0] if item.image_urls else None,
                    item.url,
                    1 if matched else 0,
                    confidence,
                    reasoning,
                    gold_type,
                    karat,
                    hallmark,
                    antique_style,
                    STATUS_NEW,
                    now,
                    now,
                ),
            )
            self._conn.commit()

    # -- re-scoring ------------------------------------------------------------

    def rescore_candidates(self, limit: int = 150) -> list[dict]:
        """Previously AI-scored rejects, newest first — the re-score backlog."""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM items
                WHERE matched = 0 AND confidence IS NOT NULL AND image_url IS NOT NULL
                ORDER BY first_seen DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def apply_rescore(
        self,
        item_id: str,
        matched: bool,
        confidence: float | None,
        reasoning: str,
        gold_type: str | None = None,
        karat: str | None = None,
        hallmark: str | None = None,
        antique_style: str | None = None,
    ) -> bool:
        """Overwrite an item's verdict; promote rejected→matched as 'new'."""
        with self._lock:
            row = self._conn.execute(
                "SELECT matched, status FROM items WHERE item_id = ?",
                (str(item_id),),
            ).fetchone()
            if row is None:
                return False
            status = row["status"]
            if matched and not row["matched"]:
                status = STATUS_NEW
            self._conn.execute(
                """
                UPDATE items SET matched = ?, confidence = ?, reasoning = ?,
                    gold_type = ?, karat = ?, hallmark = ?, antique_style = ?,
                    status = ?, updated = ?
                WHERE item_id = ?
                """,
                (
                    1 if matched else 0,
                    confidence,
                    reasoning,
                    gold_type,
                    karat,
                    hallmark,
                    antique_style,
                    status,
                    time.time(),
                    str(item_id),
                ),
            )
            self._conn.commit()
            return True

    def list_matches(self, status: str | None = None) -> list[dict]:
        query = "SELECT * FROM items WHERE matched = 1"
        params: list = []
        if status and status != "all":
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY first_seen DESC"
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_item(self, item_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM items WHERE item_id = ?", (str(item_id),)
            ).fetchone()
        return dict(row) if row else None

    def list_rejected(self, limit: int = 150) -> list[dict]:
        """Scanned items the AI rejected (or the title filter skipped).

        Scored rejects come first, highest confidence first, so near-misses are
        easiest to review; unscored (title-filtered) items follow.
        """
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM items
                WHERE matched = 0
                ORDER BY (confidence IS NULL) ASC, confidence DESC, first_seen DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def promote(self, item_id: str, status: str = STATUS_NEW) -> bool:
        """Move a rejected item into the matched candidates (user override)."""
        if status not in VALID_STATUSES:
            return False
        with self._lock:
            cur = self._conn.execute(
                "UPDATE items SET matched = 1, status = ?, updated = ? WHERE item_id = ?",
                (status, time.time(), str(item_id)),
            )
            self._conn.commit()
            return cur.rowcount > 0

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

    def labeling_queue(self, limit: int = 40) -> list[dict]:
        """Items with a photo that haven't been labeled yet (matched first)."""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT i.* FROM items i
                LEFT JOIN examples e ON e.image_url = i.image_url
                WHERE i.image_url IS NOT NULL AND e.id IS NULL
                ORDER BY i.matched DESC, i.first_seen DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # -- training examples ---------------------------------------------------

    def add_example(
        self,
        image_url: str,
        label: str,
        item_id: str | None = None,
        title: str | None = None,
        note: str | None = None,
    ) -> dict | None:
        if label not in VALID_LABELS or not image_url:
            return None
        now = time.time()
        with self._lock:
            # Upsert on image_url so re-labeling flips the label instead of erroring.
            self._conn.execute(
                """
                INSERT INTO examples (item_id, title, image_url, label, note, created)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(image_url) DO UPDATE SET
                    label = excluded.label,
                    note = COALESCE(excluded.note, examples.note),
                    item_id = COALESCE(excluded.item_id, examples.item_id),
                    title = COALESCE(excluded.title, examples.title)
                """,
                (item_id, title, image_url, label, note, now),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT * FROM examples WHERE image_url = ?", (image_url,)
            ).fetchone()
        return dict(row) if row else None

    def list_examples(self, label: str | None = None) -> list[dict]:
        query = "SELECT * FROM examples"
        params: list = []
        if label in VALID_LABELS:
            query += " WHERE label = ?"
            params.append(label)
        query += " ORDER BY created DESC"
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def delete_example(self, example_id: int) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM examples WHERE id = ?", (example_id,))
            self._conn.commit()
            return cur.rowcount > 0

    def example_counts(self) -> dict:
        with self._lock:
            rows = self._conn.execute(
                "SELECT label, COUNT(*) AS n FROM examples GROUP BY label"
            ).fetchall()
        by = {r["label"]: r["n"] for r in rows}
        return {
            "positive": int(by.get(LABEL_POSITIVE, 0)),
            "negative": int(by.get(LABEL_NEGATIVE, 0)),
            "total": int(sum(by.values())),
        }

    # -- settings ------------------------------------------------------------

    def get_setting(self, key: str, default: str = "") -> str:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row and row["value"] is not None else default

    def set_setting(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            self._conn.commit()

    # -- stats ---------------------------------------------------------------

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
            "rejected": int(total_seen) - int(matched_total),
            "new": int(by_status.get(STATUS_NEW, 0)),
            "favorite": int(by_status.get(STATUS_FAVORITE, 0)),
            "dismissed": int(by_status.get(STATUS_DISMISSED, 0)),
        }

    def count(self) -> int:
        return self.counts()["seen"]

    def close(self) -> None:
        with self._lock:
            self._conn.close()
