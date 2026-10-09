from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class OfflineQueue:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()

    def _conn(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pending_quotes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dedup_key TEXT UNIQUE NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()

    @staticmethod
    def dedup_key(payload: dict[str, Any]) -> str:
        return f"{payload.get('option_symbol','')}|{payload.get('quote_timestamp','')}"

    def enqueue_many(self, rows: list[dict[str, Any]]) -> int:
        inserted = 0
        with self._conn() as conn:
            for row in rows:
                key = self.dedup_key(row)
                try:
                    conn.execute(
                        "INSERT INTO pending_quotes(dedup_key, payload_json) VALUES (?, ?)",
                        (key, json.dumps(row, ensure_ascii=False)),
                    )
                    inserted += 1
                except sqlite3.IntegrityError:
                    pass
            conn.commit()
        return inserted

    def dequeue_batch(self, batch_size: int) -> list[tuple[int, dict[str, Any]]]:
        with self._conn() as conn:
            cur = conn.execute("SELECT id, payload_json FROM pending_quotes ORDER BY id ASC LIMIT ?", (batch_size,))
            rows = [(rid, json.loads(payload)) for rid, payload in cur.fetchall()]
        return rows

    def ack_ids(self, ids: list[int]) -> None:
        if not ids:
            return
        marks = ",".join("?" for _ in ids)
        with self._conn() as conn:
            conn.execute(f"DELETE FROM pending_quotes WHERE id IN ({marks})", ids)
            conn.commit()

    def size(self) -> int:
        with self._conn() as conn:
            cur = conn.execute("SELECT COUNT(*) FROM pending_quotes")
            return int(cur.fetchone()[0])
