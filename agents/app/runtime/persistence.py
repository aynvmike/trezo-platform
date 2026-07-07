"""Batched async persistence of agent messages to Supabase.

Created 2026-06-05 as Task #61: replaces per-message INSERT with a
buffered batch model. Reduces Supabase round-trips by ~50x:

  - persist_message() appends to an in-memory deque (fast, non-blocking)
  - Background flush loop bulk-inserts every FLUSH_INTERVAL seconds OR
    when buffer hits FLUSH_MAX_BATCH messages
  - Bulk insert = single Supabase POST with array of rows

Best-effort: any failure inside the flush is logged + buffer drained
(so a Supabase blip doesn't grow the buffer forever).
"""

from __future__ import annotations

import asyncio
from collections import deque
from typing import Optional, Any

from app.agents.base import AgentMessage
from app.config import get_settings


_supabase = None  # lazy
_buffer: deque = deque()
_buffer_lock = asyncio.Lock()
_flush_task: Optional[asyncio.Task] = None

# Tuning - 1 second flush cadence, max batch size 50.
# A 5-scanner busy tick emits maybe 100 messages across all scanners
# in a single second; this lets one bulk insert handle them all.
FLUSH_INTERVAL_SECONDS = 1.0
FLUSH_MAX_BATCH = 50
FLUSH_HARD_CAP = 500   # safety: never let buffer exceed this in a single flush


def _client():
    global _supabase
    if _supabase is not None:
        return _supabase
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_role_key:
        return None
    try:
        from supabase import create_client
        _supabase = create_client(settings.supabase_url, settings.supabase_service_role_key)
        return _supabase
    except Exception:  # noqa: BLE001
        return None


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
    """Queue a message for batched persistence. Returns immediately.
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
            _k = f"{message.agent}|{message.kind}"
            _HB_SEEN[_k] = _HB_SEEN.get(_k, 0) + 1
            if _HB_SEEN[_k] % 5 != 1:
                return
    except Exception:  # noqa: BLE001
        pass
    row = {
        "user_id": user_id,
        "agent_name": message.agent,
        "kind": message.kind,
        "confidence": message.confidence,
        "payload": message.payload,
    }
    async with _buffer_lock:
        _buffer.append(row)
        should_flush_now = len(_buffer) >= FLUSH_MAX_BATCH
    if should_flush_now:
        # Don't await - let the flush run concurrently while caller continues
        asyncio.create_task(flush_buffer())


async def flush_buffer() -> int:
    """Drain the buffer into one bulk Supabase INSERT. Returns count
    of rows actually written. Idempotent: safe to call when empty."""
    async with _buffer_lock:
        if not _buffer:
            return 0
        batch = []
        while _buffer and len(batch) < FLUSH_HARD_CAP:
            batch.append(_buffer.popleft())
    if not batch:
        return 0

    client = _client()
    if not client:
        # No DB available - drop the batch but log it.
        print(f"[persistence] no Supabase client; dropped {len(batch)} messages")
        return 0

    def _sync():
        try:
            client.table("agent_messages").insert(batch).execute()
            return len(batch)
        except Exception as e:  # noqa: BLE001
            print(f"[persistence] batch insert FAILED ({len(batch)} rows): {e}")
            return 0

    return await asyncio.to_thread(_sync)


async def _flush_loop() -> None:
    """Background task: flush every FLUSH_INTERVAL_SECONDS."""
    while True:
        try:
            await asyncio.sleep(FLUSH_INTERVAL_SECONDS)
            await flush_buffer()
        except asyncio.CancelledError:
            # Last-chance flush before we stop entirely
            try:
                await flush_buffer()
            except Exception:  # noqa: BLE001
                pass
            raise
        except Exception as e:  # noqa: BLE001
            print(f"[persistence] flush loop error: {e}")


def start_flush_loop() -> Optional[asyncio.Task]:
    """Start the background flush loop. Idempotent - safe to call
    repeatedly (e.g. on uvicorn reload). Returns the task handle."""
    global _flush_task
    if _flush_task is not None and not _flush_task.done():
        return _flush_task
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No loop running yet - caller must invoke from within the loop
        return None
    _flush_task = loop.create_task(_flush_loop())
    return _flush_task


async def stop_flush_loop() -> None:
    """Cancel the background flush loop. Performs one final drain."""
    global _flush_task
    if _flush_task is None:
        return
    _flush_task.cancel()
    try:
        await _flush_task
    except (asyncio.CancelledError, Exception):  # noqa: BLE001
        pass
    _flush_task = None
    # One last drain in case anything queued after the loop's final flush
    try:
        await flush_buffer()
    except Exception:  # noqa: BLE001
        pass


def buffer_stats() -> dict[str, int]:
    """Diagnostic: peek at buffer state. Safe to call from anywhere."""
    return {
        "buffered": len(_buffer),
        "flush_max": FLUSH_MAX_BATCH,
        "flush_interval_s": int(FLUSH_INTERVAL_SECONDS),
    }
