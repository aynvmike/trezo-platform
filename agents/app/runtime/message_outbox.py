"""Bounded, durable delivery queue for agent_messages, never trading commands.

SQLite lives on the engine host, outside the cloud database. Acknowledgement
removes only rows accepted by Supabase; a crash after the remote commit can
therefore retry the same UUID safely. No payloads or credentials are logged.
"""
from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import threading
import time


class MessageOutbox:
    def __init__(self, path: Path, *, max_rows: int = 20_000,
                 max_bytes: int = 32 * 1024 * 1024,
                 book_max_rows: int = 5_000,
                 book_max_bytes: int = 8 * 1024 * 1024,
                 max_row_bytes: int = 64 * 1024,
                 retention_seconds: float = 14 * 86400,
                 max_file_bytes: int = 64 * 1024 * 1024):
        self.path = Path(path)
        self.max_rows = max_rows
        self.max_bytes = max_bytes
        self.book_max_rows = book_max_rows
        self.book_max_bytes = book_max_bytes
        self.max_row_bytes = max_row_bytes
        self.retention_seconds = retention_seconds
        self.max_file_bytes = max_file_bytes
        self._lock = threading.RLock()
        self._initialized = False
        self._last_prune = float("-inf")

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(str(self.path), timeout=1.0)
        try:
            # DELETE avoids a growing WAL during a prolonged cloud outage.
            # The rollback journal is bounded by pages in this capped database;
            # pruning can touch more than one row in a transaction.
            db.execute("PRAGMA journal_mode=DELETE")
            db.execute("PRAGMA synchronous=FULL")
            pages = max(16, self.max_file_bytes // db.execute("PRAGMA page_size").fetchone()[0])
            db.execute(f"PRAGMA max_page_count={pages}")
            if not self._initialized:
                db.executescript("""
                    CREATE TABLE IF NOT EXISTS pending (
                        seq INTEGER PRIMARY KEY,
                        id TEXT NOT NULL UNIQUE,
                        book TEXT NOT NULL,
                        queued_at REAL NOT NULL,
                        nbytes INTEGER NOT NULL,
                        row_json TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS pending_book_seq ON pending(book, seq);
                    CREATE TABLE IF NOT EXISTS losses (
                        book TEXT NOT NULL,
                        reason TEXT NOT NULL,
                        count INTEGER NOT NULL,
                        PRIMARY KEY (book, reason)
                    );
                """)
                self._initialized = True
            return db
        except BaseException:
            db.close()
            raise

    @staticmethod
    def _loss(db, book: str, reason: str, count: int = 1):
        db.execute("""INSERT INTO losses(book, reason, count) VALUES (?, ?, ?)
                      ON CONFLICT(book, reason) DO UPDATE SET count=count+excluded.count""",
                   (book, reason, count))

    def _prune(self, db, now: float):
        if now - self._last_prune < 60:
            return
        cutoff = now - self.retention_seconds
        for book, count in db.execute(
                "SELECT book, count(*) FROM pending WHERE queued_at < ? GROUP BY book",
                (cutoff,)).fetchall():
            self._loss(db, book, "expired", count)
        db.execute("DELETE FROM pending WHERE queued_at < ?", (cutoff,))
        self._last_prune = now

    def enqueue(self, row: dict, *, now: float | None = None) -> bool:
        """Durably save before returning; reject new excess rows, never evict another book."""
        book = str(row.get("user_id") or "")
        try:
            encoded = json.dumps(row, separators=(",", ":"), allow_nan=False)
            nbytes = len(encoded.encode("utf-8"))
            reason = "oversize" if nbytes > self.max_row_bytes else None
        except (TypeError, ValueError):
            encoded, nbytes, reason = "", 0, "invalid_json"
        now = time.time() if now is None else now
        with self._lock, closing(self._connect()) as db, db:
            self._prune(db, now)
            if reason:
                self._loss(db, book, reason)
                return False
            if db.execute("SELECT 1 FROM pending WHERE id=?", (row["id"],)).fetchone():
                return True
            rows, size = db.execute("SELECT count(*), coalesce(sum(nbytes),0) FROM pending").fetchone()
            book_rows, book_size = db.execute(
                "SELECT count(*), coalesce(sum(nbytes),0) FROM pending WHERE book=?", (book,)).fetchone()
            if (book_rows >= self.book_max_rows or book_size + nbytes > self.book_max_bytes
                    or rows >= self.max_rows or size + nbytes > self.max_bytes):
                self._loss(db, book, "capacity")
                return False
            db.execute("INSERT INTO pending(id, book, queued_at, nbytes, row_json) VALUES (?, ?, ?, ?, ?)",
                       (row["id"], book, now, nbytes, encoded))
            return True

    def books(self) -> list[str]:
        with self._lock, closing(self._connect()) as db, db:
            self._prune(db, time.time())
            return [r[0] for r in db.execute("SELECT book FROM pending GROUP BY book ORDER BY min(seq)")]

    def batch(self, book: str, limit: int) -> list[dict]:
        with self._lock, closing(self._connect()) as db:
            return [json.loads(r[0]) for r in db.execute(
                "SELECT row_json FROM pending WHERE book=? ORDER BY seq LIMIT ?", (book, limit))]

    def acknowledge(self, ids: list[str]) -> None:
        with self._lock, closing(self._connect()) as db, db:
            db.executemany("DELETE FROM pending WHERE id=?", ((item,) for item in ids))

    def stats(self) -> dict[str, int]:
        with self._lock, closing(self._connect()) as db:
            count, size = db.execute("SELECT count(*), coalesce(sum(nbytes),0) FROM pending").fetchone()
            losses = dict(db.execute("SELECT reason, sum(count) FROM losses GROUP BY reason"))
            return {"buffered": count, "pending_bytes": size,
                    "dropped": sum(losses.values()),
                    **{f"dropped_{reason}": value for reason, value in losses.items()}}
