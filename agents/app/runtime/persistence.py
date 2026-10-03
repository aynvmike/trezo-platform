"""Durable, bounded telemetry delivery to Supabase.

persist_message writes a local SQLite outbox before returning. The existing
engine flush loop forwards per-book batches with bounded retry backoff. Stable
UUIDs make a remote commit followed by a lost response safe to replay. Original
message timestamps prevent replayed history appearing to be fresh heartbeats.

Only agent_messages are retried: nothing is republished on the agent bus and no
orders, approvals, settings, ledger updates or other trading work is replayed.
"""
from __future__ import annotations

import asyncio
from datetime import timezone
from pathlib import Path
import time
from typing import Optional
from uuid import uuid4

from app.agents.base import AgentMessage
from app.config import get_settings
from .message_outbox import MessageOutbox


_supabase = None
_outbox: Optional[MessageOutbox] = None
_flush_task: Optional[asyncio.Task] = None
_flush_lock = asyncio.Lock()
_retry: dict[str, tuple[int, float]] = {}
_local_write_failures = 0
_last_warning: dict[str, float] = {}
_now = time.monotonic

# A bounded recovery rate, not a burst of the entire outage into the database.
FLUSH_INTERVAL_SECONDS = 5.0
FLUSH_MAX_BATCH = 50
RETRY_BASE_SECONDS = 5.0
RETRY_MAX_SECONDS = 300.0


def _queue() -> MessageOutbox:
    global _outbox
    if _outbox is None:
        _outbox = MessageOutbox(Path(__file__).resolve().parents[2]
                               / "local_state" / "agent_messages.sqlite3")
    return _outbox


def _warn(reason: str, error: Exception | None = None) -> None:
    # Never print an exception's message: SDK errors may echo a payload or URL.
    now = _now()
    if now - _last_warning.get(reason, float("-inf")) >= 60:
        _last_warning[reason] = now
        detail = f" ({type(error).__name__})" if error else ""
        print(f"[persistence] {reason}{detail}; inspect buffer_stats for backlog/loss counts")


def _client():
    global _supabase
    if _supabase is not None:
        return _supabase
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_role_key:
        return None
    from supabase import create_client
    from supabase.lib.client_options import ClientOptions
    _supabase = create_client(
        settings.supabase_url, settings.supabase_service_role_key,
        options=ClientOptions(postgrest_client_timeout=10))
    return _supabase


# Task #59 (2026-06-05): persistence filter. Read from config so the
# user can flip skip_signal_persist=false in agents/.env if they want
# every signal in the DB.
_skip_kinds_cached = None
def _skip_persist_kinds() -> set:
    global _skip_kinds_cached
    if _skip_kinds_cached is not None:
        return _skip_kinds_cached
    s = get_settings()
    out = set()
    if getattr(s, "skip_signal_persist", True):
        out.add("signal")
    _skip_kinds_cached = out
    return out


_HB_SEEN: dict[str, int] = {}   # telemetry-diet counters (2026-07-07)


async def persist_message(message: AgentMessage, user_id: Optional[str] = None) -> None:
    """Queue a message for batched persistence. Returns after the local durable write (no cloud I/O).
    Filters out kinds in SKIP_PERSIST_KINDS (signal by default - the
    scanner_pulse summary row covers what the trace panel needs)."""
    if message.kind in _skip_persist_kinds():
        return
    # Telemetry diet (2026-07-07): heartbeat chatter (idle scanner pulses,
    # "Position check", "scan complete" notes) regrew agent_messages to
    # 266k rows and pinned the nano DB's CPU. Keep 1 in 5 per agent;
    # anything carrying real news (fires, signals, breakouts) always
    # persists, as do vetoes/approvals/errors/closes.
    try:
        _p = message.payload or {}
        _hb = False
        if message.kind == "scanner_pulse":
            _hb = not (_p.get("fired") or _p.get("signals")
                       or _p.get("breakouts") or _p.get("modes_triggered"))
        elif message.kind == "info":
            _note = str(_p.get("note") or "")
            _hb = _note.startswith((
                "Position check", "Crypto scan complete", "ORB scan complete",
                "Extended scan complete", "Outside", "No open position",
                "Forex DISABLED"))
        if _hb:
            _k = f"{user_id or 'unattributed'}|{message.agent}|{message.kind}"
            _HB_SEEN[_k] = _HB_SEEN.get(_k, 0) + 1
            if _HB_SEEN[_k] % 5 != 1:
                return
    except Exception:  # noqa: BLE001
        pass
    global _local_write_failures
    try:
        stamp = message.timestamp
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        row = {
            "id": str(uuid4()),
            "created_at": stamp.astimezone(timezone.utc).isoformat(),
            "user_id": user_id,
            "agent_name": message.agent,
            "kind": message.kind,
            "confidence": message.confidence,
            "payload": message.payload,
        }
        saved = await asyncio.to_thread(_queue().enqueue, row)
        if not saved:
            _warn("local outbox limit/serialization rejection; telemetry not saved")
    except Exception as error:  # reporting must never stop the trading bus
        _local_write_failures += 1
        _warn("local outbox write failed; telemetry not saved", error)


def _backoff(book: str) -> None:
    failures = min(_retry.get(book, (0, 0))[0] + 1, 10)
    delay = min(RETRY_BASE_SECONDS * 2 ** (failures - 1), RETRY_MAX_SECONDS)
    _retry[book] = (failures, _now() + delay)


async def flush_buffer() -> int:
    """Send bounded per-book batches; keep unacknowledged rows across restarts.

    A reject on one book does not block another. Retry timing is independent
    per book; concurrent callers cannot deliver/ack competing snapshots.
    """
    if _flush_lock.locked():
        return 0
    async with _flush_lock:
        try:
            queue = _queue()
            books = await asyncio.to_thread(queue.books)
            written = 0
            for book in books:
                if _now() < _retry.get(book, (0, 0))[1]:
                    continue
                batch = await asyncio.to_thread(queue.batch, book, FLUSH_MAX_BATCH)
                if not batch:
                    _retry.pop(book, None)
                    continue
                try:
                    def _send():
                        client = _client()
                        if client is None:
                            raise RuntimeError("Supabase is not configured")
                        # agent_messages.id is its UUID primary key (migration
                        # 0007); duplicate-ignore never overwrites an existing row.
                        client.table("agent_messages").upsert(
                            batch, on_conflict="id", ignore_duplicates=True).execute()
                    await asyncio.to_thread(_send)
                    await asyncio.to_thread(queue.acknowledge, [row["id"] for row in batch])
                    written += len(batch)
                    _retry.pop(book, None)
                except Exception as error:
                    _backoff(book)
                    _warn("remote delivery unconfirmed; retained locally for retry", error)
            return written
        except Exception as error:
            _warn("local outbox read/ack failed; pending rows retained", error)
            return 0


async def _flush_loop() -> None:
    while True:
        try:
            # Starts by replaying any durable backlog from the previous process.
            await flush_buffer()
            await asyncio.sleep(FLUSH_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            _warn("flush loop failed", error)
            await asyncio.sleep(FLUSH_INTERVAL_SECONDS)


def start_flush_loop() -> Optional[asyncio.Task]:
    """Existing engine startup hook; idempotent within this process."""
    global _flush_task
    if _flush_task is not None and not _flush_task.done():
        return _flush_task
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None
    _flush_task = loop.create_task(_flush_loop())
    return _flush_task


async def stop_flush_loop() -> None:
    """Stop delivery; committed local rows do not need a cloud shutdown flush."""
    global _flush_task
    if _flush_task is None:
        return
    _flush_task.cancel()
    try:
        await _flush_task
    except asyncio.CancelledError:
        pass
    _flush_task = None


def buffer_stats() -> dict[str, int]:
    """Aggregate diagnostics only: no book identifiers, payloads or secrets."""
    out = {"flush_max": FLUSH_MAX_BATCH,
           "flush_interval_s": int(FLUSH_INTERVAL_SECONDS),
           "local_write_failures": _local_write_failures,
           "retrying_books": sum(1 for _, at in _retry.values() if at > _now()),
           "available": 1}
    try:
        # A health read before first use must not create an empty database.
        if _outbox is None:
            path = Path(__file__).resolve().parents[2] / "local_state" / "agent_messages.sqlite3"
            if not path.exists():
                return {**out, "buffered": 0, "pending_bytes": 0, "dropped": 0}
        return {**out, **_queue().stats()}
    except Exception:
        # Unknown is not empty. -1 is distinguishable from a healthy zero.
        return {**out, "available": 0, "buffered": -1, "pending_bytes": -1, "dropped": -1}
