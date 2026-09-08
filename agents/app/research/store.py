"""Durable, single-engine SQLite pilot queue with immutable research rows."""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import time
import uuid

from .core import canonical, digest

SCHEMA = """
CREATE TABLE IF NOT EXISTS research_jobs (
  job_id TEXT PRIMARY KEY, book_id TEXT NOT NULL,
  request_json TEXT NOT NULL, status TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0, lease_until REAL,
  lease_token TEXT, result_json TEXT, error TEXT,
  created_at REAL NOT NULL, updated_at REAL NOT NULL,
  CHECK(status IN ('queued','running','completed','failed'))
);
CREATE TABLE IF NOT EXISTS research_candidates (
  candidate_id TEXT PRIMARY KEY, book_id TEXT NOT NULL,
  parent_id TEXT REFERENCES research_candidates(candidate_id), spec_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS research_trials (
  job_id TEXT NOT NULL REFERENCES research_jobs(job_id),
  candidate_id TEXT NOT NULL REFERENCES research_candidates(candidate_id),
  result_json TEXT NOT NULL, PRIMARY KEY(job_id, candidate_id)
);
CREATE TABLE IF NOT EXISTS research_events (
  job_id TEXT NOT NULL REFERENCES research_jobs(job_id), event_key TEXT NOT NULL,
  payload_json TEXT NOT NULL, created_at REAL NOT NULL,
  PRIMARY KEY(job_id, event_key)
);
"""


class LeaseLost(RuntimeError):
    pass


class Store:
    def __init__(self, path, *, lease_seconds=300, max_attempts=3):
        if not 1 <= max_attempts <= 5 or not 1 <= lease_seconds <= 1800:
            raise ValueError("invalid research queue retry or lease bounds")
        self.path = str(path)
        if self.path == ":memory:":
            raise ValueError("research queue requires a durable file")
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts
        with self.connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(SCHEMA)

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def claim(self, job_id, book_id, request) -> dict:
        now = time.time()
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("""INSERT OR IGNORE INTO research_jobs
              (job_id, book_id, request_json, status, created_at, updated_at)
              VALUES (?, ?, ?, 'queued', ?, ?)""",
                               (job_id, book_id, canonical(request), now, now))
            row = dict(connection.execute("SELECT * FROM research_jobs WHERE job_id=?", (job_id,)).fetchone())
            if row["book_id"] != book_id:
                raise ValueError("research job belongs to another book")
            if row["status"] == "completed":
                return {"status": "completed", "result": json.loads(row["result_json"])}
            if row["status"] == "running" and row["lease_until"] > now:
                return {"status": "busy", "attempts": row["attempts"]}
            if row["attempts"] >= self.max_attempts:
                connection.execute("UPDATE research_jobs SET status='failed', updated_at=? WHERE job_id=?", (now, job_id))
                return {"status": "failed", "attempts": row["attempts"],
                        "error": "research retry budget exhausted"}
            token = uuid.uuid4().hex
            attempt = row["attempts"] + 1
            connection.execute("""UPDATE research_jobs SET status='running', attempts=?,
              lease_token=?, lease_until=?, error=NULL, updated_at=? WHERE job_id=?""",
                               (attempt, token, now + self.lease_seconds, now, job_id))
            self._event(connection, job_id, f"claim:{attempt}", {"attempt": attempt}, now)
            return {"status": "claimed", "token": token, "attempts": attempt,
                    "request": json.loads(row["request_json"])}

    def _own(self, connection, job_id, token):
        row = connection.execute("SELECT * FROM research_jobs WHERE job_id=?", (job_id,)).fetchone()
        if row is None or row["status"] != "running" or row["lease_token"] != token:
            raise LeaseLost("research lease no longer belongs to this worker")
        return row

    def _event(self, connection, job_id, event_key, payload, now):
        body = canonical(payload)
        prior = connection.execute("SELECT payload_json FROM research_events WHERE job_id=? AND event_key=?",
                                   (job_id, event_key)).fetchone()
        if prior and prior["payload_json"] != body:
            raise ValueError("immutable research event conflict")
        connection.execute("INSERT OR IGNORE INTO research_events VALUES (?, ?, ?, ?)",
                           (job_id, event_key, body, now))

    def candidate(self, job_id, token, candidate_id, spec):
        if digest(spec) != candidate_id:
            raise ValueError("candidate content does not match its immutable hash")
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._own(connection, job_id, token)
            if spec["book_id"] != row["book_id"]:
                raise ValueError("candidate belongs to another book")
            parent_id = spec.get("parent_id")
            if parent_id:
                parent = connection.execute("SELECT book_id FROM research_candidates WHERE candidate_id=?", (parent_id,)).fetchone()
                if parent is None or parent["book_id"] != row["book_id"]:
                    raise ValueError("candidate parent is missing or belongs to another book")
            body = canonical(spec)
            prior = connection.execute("SELECT spec_json FROM research_candidates WHERE candidate_id=?", (candidate_id,)).fetchone()
            if prior and prior["spec_json"] != body:
                raise ValueError("immutable candidate conflict")
            connection.execute("INSERT OR IGNORE INTO research_candidates VALUES (?, ?, ?, ?)",
                               (candidate_id, row["book_id"], parent_id, body))
            self._event(connection, job_id, f"candidate:{candidate_id}",
                        {"candidate_id": candidate_id, "parent_id": parent_id}, time.time())

    def trial(self, job_id, token, candidate_id, result):
        if result.get("candidate_id") != candidate_id or result.get("state") not in {"rejected", "shadow_candidate"}:
            raise ValueError("trial must describe a research-only candidate result")
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            job = self._own(connection, job_id, token)
            candidate = connection.execute("SELECT book_id FROM research_candidates WHERE candidate_id=?", (candidate_id,)).fetchone()
            if candidate is None or candidate["book_id"] != job["book_id"]:
                raise ValueError("trial candidate belongs to another book")
            body = canonical(result)
            prior = connection.execute("SELECT result_json FROM research_trials WHERE job_id=? AND candidate_id=?",
                                       (job_id, candidate_id)).fetchone()
            if prior and prior["result_json"] != body:
                raise ValueError("immutable trial conflict")
            connection.execute("INSERT OR IGNORE INTO research_trials VALUES (?, ?, ?)", (job_id, candidate_id, body))
            now = time.time()
            self._event(connection, job_id, f"trial:{candidate_id}",
                        {"candidate_id": candidate_id, "state": result["state"]}, now)
            connection.execute("UPDATE research_jobs SET lease_until=?, updated_at=? WHERE job_id=?",
                               (now + self.lease_seconds, now, job_id))

    def prior_training_candidate(self, book_id, lineage_scope, cutoff) -> dict | None:
        """Carry a prior rule forward using training evidence only.

        Find the most recent completed cycle in the caller's lineage scope.
        Fixed scenarios isolate capital; broker-equity scopes isolate the
        account source and costs while allowing the balance to change.
        Validation results and screening state are never selectors.
        Future training windows cannot seed an earlier historical cycle.
        """
        with self.connection() as connection:
            rows = connection.execute("""SELECT job_id, request_json FROM research_jobs
              WHERE book_id=? AND status='completed' ORDER BY created_at DESC, job_id DESC LIMIT 200""",
                                      (book_id,)).fetchall()
            for row in rows:
                request = json.loads(row["request_json"])
                if request.get("lineage_scope") != lineage_scope:
                    continue
                if request["candles"][request["split_index"] - 1]["timestamp"] > cutoff:
                    continue
                trials = [json.loads(item["result_json"]) for item in connection.execute(
                    "SELECT result_json FROM research_trials WHERE job_id=?", (row["job_id"],)).fetchall()]
                if trials:
                    best = max(trials, key=lambda trial: (trial["train"]["net_pnl_usd"], trial["candidate_id"]))
                    return {"source_job_id": row["job_id"], "candidate_id": best["candidate_id"], "spec": best["spec"]}
        return None

    def finish(self, job_id, token, result):
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._own(connection, job_id, token)
            now = time.time()
            self._event(connection, job_id, "completed", {"trial_count": len(result["trials"])}, now)
            connection.execute("""UPDATE research_jobs SET status='completed', result_json=?,
              lease_until=NULL, lease_token=NULL, updated_at=? WHERE job_id=?""", (canonical(result), now, job_id))

    def fail(self, job_id, token, error):
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._own(connection, job_id, token)
            now = time.time()
            self._event(connection, job_id, f"failed:{row['attempts']}", {"error": error}, now)
            connection.execute("""UPDATE research_jobs SET status='failed', error=?,
              lease_until=NULL, lease_token=NULL, updated_at=? WHERE job_id=?""", (error, now, job_id))
