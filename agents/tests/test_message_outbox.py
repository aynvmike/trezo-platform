"""Drive the real persistence subscriber/flush path without keys or network."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager, redirect_stdout
from datetime import datetime, timezone
import io
import sqlite3
from pathlib import Path
import sys
import tempfile
from uuid import UUID, uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import load_module, run_tests, stub_config  # noqa: E402

stub_config()
base = load_module("app.agents.base")
outbox_module = load_module("app.runtime.message_outbox")
p = load_module("app.runtime.persistence")
MessageOutbox = outbox_module.MessageOutbox


class _Remote:
    def __init__(self):
        self.rows = {}
        self.calls = []
        self.fail_books = set()
        self.fail_after_commit = False

    def table(self, name):
        assert name == "agent_messages", "outbox must never replay orders or other tables"
        return self

    def upsert(self, rows, *, on_conflict, ignore_duplicates):
        assert on_conflict == "id" and ignore_duplicates is True
        self.batch = list(rows)
        return self

    def execute(self):
        self.calls.append(self.batch)
        if self.batch[0]["user_id"] in self.fail_books:
            raise RuntimeError("DO-NOT-PRINT secret payload/url example")
        for row in self.batch:
            self.rows.setdefault(row["id"], row)
        if self.fail_after_commit:
            self.fail_after_commit = False
            raise TimeoutError("commit succeeded, response lost")
        return object()


@contextmanager
def _runtime(path, remote=None, **queue_options):
    old = {name: getattr(p, name) for name in (
        "_outbox", "_supabase", "_retry", "_flush_lock", "_flush_task",
        "_local_write_failures", "_last_warning", "_now", "_skip_kinds_cached", "_HB_SEEN")}
    clock = [1000.0]
    p._outbox = MessageOutbox(path, **queue_options)
    p._supabase = remote or _Remote()
    p._retry = {}
    p._flush_lock = asyncio.Lock()
    p._flush_task = None
    p._local_write_failures = 0
    p._last_warning = {}
    p._now = lambda: clock[0]
    p._skip_kinds_cached = {"signal"}
    p._HB_SEEN = {}
    try:
        yield clock
    finally:
        for name, value in old.items():
            setattr(p, name, value)


def _message(kind="veto", **payload):
    return base.AgentMessage(agent="risk_manager", kind=kind, payload=payload,
                             timestamp=datetime(2026, 10, 2, 10, 2, 16, tzinfo=timezone.utc))


def _row(book="book-a", **overrides):
    return {"id": str(uuid4()), "user_id": book, "kind": "veto", "payload": {}, **overrides}


def test_restart_replays_original_book_id_and_event_time():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "queue.sqlite3"
        failed = _Remote()
        failed.fail_books.add("book-a")
        with _runtime(path, failed):
            asyncio.run(p.persist_message(_message(reason="disabled"), "book-a"))
            assert asyncio.run(p.flush_buffer()) == 0
            stored = p._outbox.batch("book-a", 50)[0]
            UUID(stored["id"])
            assert stored["created_at"] == "2026-10-02T10:02:16+00:00"
            assert p.buffer_stats()["buffered"] == 1
        healthy = _Remote()
        with _runtime(path, healthy):
            assert asyncio.run(p.flush_buffer()) == 1
            assert healthy.rows[stored["id"]] == stored
            assert p.buffer_stats()["buffered"] == 0


def test_remote_commit_then_lost_response_retries_without_duplicate():
    with tempfile.TemporaryDirectory() as td:
        remote = _Remote()
        remote.fail_after_commit = True
        with _runtime(Path(td) / "queue.sqlite3", remote) as clock:
            asyncio.run(p.persist_message(_message(), "book-a"))
            assert asyncio.run(p.flush_buffer()) == 0
            assert len(remote.rows) == 1 and p.buffer_stats()["buffered"] == 1
            clock[0] += 5
            assert asyncio.run(p.flush_buffer()) == 1
            assert len(remote.rows) == 1 and p.buffer_stats()["buffered"] == 0
            assert remote.calls[0] == remote.calls[1]


def test_failure_is_backed_off_and_does_not_block_other_book():
    with tempfile.TemporaryDirectory() as td:
        remote = _Remote()
        remote.fail_books.add("book-a")
        with _runtime(Path(td) / "queue.sqlite3", remote) as clock:
            asyncio.run(p.persist_message(_message(), "book-a"))
            asyncio.run(p.persist_message(_message(), "book-b"))
            assert asyncio.run(p.flush_buffer()) == 1
            calls = len(remote.calls)
            for _ in range(10):
                assert asyncio.run(p.flush_buffer()) == 0
            assert len(remote.calls) == calls
            clock[0] += 5
            asyncio.run(p.flush_buffer())
            assert len(remote.calls) == calls + 1
            clock[0] += 9
            asyncio.run(p.flush_buffer())
            assert len(remote.calls) == calls + 1
            clock[0] += 1
            asyncio.run(p.flush_buffer())
            assert len(remote.calls) == calls + 2
            assert p.buffer_stats()["buffered"] == 1
            assert next(iter(remote.rows.values()))["user_id"] == "book-b"


def test_capacity_is_bounded_per_book_and_drop_counts_survive_restart():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "queue.sqlite3"
        q = MessageOutbox(path, book_max_rows=2)
        assert q.enqueue(_row()) and q.enqueue(_row())
        assert not q.enqueue(_row())
        assert q.enqueue(_row("book-b")), "one book must not consume another book's quota"
        fresh = MessageOutbox(path)
        assert fresh.stats()["buffered"] == 3
        assert fresh.stats()["dropped_capacity"] == 1
        assert len(fresh.batch("book-a", 50)) == 2


def test_byte_and_single_row_caps_reject_without_evicting_old_rows():
    with tempfile.TemporaryDirectory() as td:
        q = MessageOutbox(Path(td) / "queue.sqlite3", max_row_bytes=256, book_max_bytes=250)
        assert q.enqueue(_row(payload={"x": "a" * 50}))
        assert not q.enqueue(_row(payload={"x": "a" * 50}))
        assert not q.enqueue(_row(payload={"x": "a" * 1000}))
        assert q.stats()["buffered"] == 1
        assert q.stats()["dropped_capacity"] == 1
        assert q.stats()["dropped_oversize"] == 1


def test_retention_expires_with_explicit_persistent_loss_count():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "queue.sqlite3"
        q = MessageOutbox(path, retention_seconds=60)
        assert q.enqueue(_row(), now=100)
        assert q.enqueue(_row("book-b"), now=161)
        assert q.stats()["buffered"] == 1
        assert MessageOutbox(path).stats()["dropped_expired"] == 1


def test_ack_deletes_only_snapshot_and_same_id_enqueue_is_idempotent():
    with tempfile.TemporaryDirectory() as td:
        q = MessageOutbox(Path(td) / "queue.sqlite3")
        first, second = _row(), _row()
        assert q.enqueue(first) and q.enqueue(first)
        snapshot = q.batch("book-a", 50)
        assert q.enqueue(second)
        q.acknowledge([r["id"] for r in snapshot])
        assert q.batch("book-a", 50) == [second]


def test_invalid_json_is_counted_without_poisoning_following_rows():
    with tempfile.TemporaryDirectory() as td:
        q = MessageOutbox(Path(td) / "queue.sqlite3")
        assert not q.enqueue(_row(payload={"score": float("nan")}))
        assert q.enqueue(_row())
        assert q.stats()["buffered"] == 1
        assert q.stats()["dropped_invalid_json"] == 1


def test_heartbeat_sampling_is_independent_for_each_book():
    with tempfile.TemporaryDirectory() as td:
        with _runtime(Path(td) / "queue.sqlite3"):
            for book in ("book-a", "book-b", "book-a", "book-b"):
                asyncio.run(p.persist_message(_message("scanner_pulse"), book))
            assert p._outbox.stats()["buffered"] == 2
            assert len(p._outbox.batch("book-a", 50)) == 1
            assert len(p._outbox.batch("book-b", 50)) == 1


def test_local_io_failure_does_not_raise_or_claim_empty_healthy_queue():
    class _Broken:
        def enqueue(self, row):
            raise OSError("DO-NOT-PRINT secret")
        def stats(self):
            raise OSError("DO-NOT-PRINT secret")
    with tempfile.TemporaryDirectory() as td:
        with _runtime(Path(td) / "queue.sqlite3"):
            p._outbox = _Broken()
            said = io.StringIO()
            with redirect_stdout(said):
                asyncio.run(p.persist_message(_message(), "book-a"))
                stats = p.buffer_stats()
            assert stats["available"] == 0 and stats["buffered"] == -1
            assert stats["local_write_failures"] == 1
            assert "DO-NOT-PRINT" not in said.getvalue()


def test_failed_remote_diagnostics_do_not_echo_exception_payloads():
    with tempfile.TemporaryDirectory() as td:
        remote = _Remote()
        remote.fail_books.add("book-a")
        with _runtime(Path(td) / "queue.sqlite3", remote):
            asyncio.run(p.persist_message(_message(), "book-a"))
            said = io.StringIO()
            with redirect_stdout(said):
                asyncio.run(p.flush_buffer())
            assert "RuntimeError" in said.getvalue()
            assert "DO-NOT-PRINT" not in said.getvalue()
            assert "book-a" not in str(p.buffer_stats())


def test_existing_startup_loop_replays_without_new_messages():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "queue.sqlite3"
        q = MessageOutbox(path)
        q.enqueue(_row())
        with _runtime(path):
            async def exercise():
                task = p.start_flush_loop()
                assert p.start_flush_loop() is task
                for _ in range(200):
                    if p.buffer_stats()["buffered"] == 0:
                        break
                    await asyncio.sleep(0.002)
                await p.stop_flush_loop()
                assert task.done()
                assert p.buffer_stats()["buffered"] == 0
            asyncio.run(exercise())


def test_sqlite_page_cap_rejects_growth_without_losing_committed_rows():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "queue.sqlite3"
        q = MessageOutbox(path, max_file_bytes=64 * 1024)
        accepted = 0
        for _ in range(50):
            try:
                assert q.enqueue(_row(payload={"text": "x" * 8000}))
                accepted += 1
            except sqlite3.OperationalError:
                break
        else:
            raise AssertionError("SQLite file limit did not bind")
        assert accepted > 0
        assert path.stat().st_size <= 64 * 1024
        assert q.stats()["buffered"] == accepted
        snapshot = q.batch("book-a", 1)
        q.acknowledge([snapshot[0]["id"]])
        assert q.stats()["buffered"] == accepted - 1


if __name__ == "__main__":
    sys.exit(run_tests(globals()))
