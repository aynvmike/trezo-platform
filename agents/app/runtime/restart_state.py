"""Restart-survival helpers (Mike 2026-06-10).

Several scanners maintain in-memory sets/dicts to dedupe within-day
emissions (ORB._alerted, Extended._signalled, Pattern.prev_strategy).
On agent restart these reset, so scanners can re-emit duplicates for
tickers they already handled today. These helpers re-hydrate the
state from today's already-persisted agent_messages.

Best-effort - any failure leaves the state empty (the runtime
behavior is wrong but not catastrophic; the concentration cap and
Risk Manager dedup are the last lines of defense).
"""

from __future__ import annotations

import asyncio
from typing import Iterable, Optional


def _today_start_utc_iso() -> str:
    """Returns ISO timestamp for the start of "today" in UTC. Tickers
    that signalled before today's market open get a fresh slate."""
    from datetime import datetime, timezone, timedelta
    # Use UTC midnight as the boundary; aligns with how created_at
    # is stored in agent_messages. Slightly conservative (re-seeds
    # signals up to 24h old) but harmless for dedup purposes.
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.isoformat().replace("+00:00", "Z")


async def seed_today_signal_tickers(agent_name: str) -> set[str]:
    """Return the set of ticker symbols this agent already emitted
    signal messages for since UTC midnight. Used to seed in-memory
    dedup state on agent startup."""
    out: set[str] = set()
    try:
        from app.runtime.persistence import _client
        client = _client()
        if client is None:
            return out

        cutoff = _today_start_utc_iso()

        def _fetch():
            return client.table("agent_messages").select("payload").eq(
                "agent_name", agent_name
            ).eq("kind", "signal").gte("created_at", cutoff).execute()

        res = await asyncio.to_thread(_fetch)
        for row in (res.data or []):
            p = row.get("payload") or {}
            t = (p.get("ticker") or "").strip().upper()
            if t:
                out.add(t)
    except Exception:  # noqa: BLE001
        pass
    return out


async def seed_today_ticker_strategy_map(agent_name: str) -> dict[str, str]:
    """Return ticker -> last strategy emitted today. Used by Pattern
    Detection's _prev_strategy to keep strategy-switching friction
    correct across restarts."""
    out: dict[str, str] = {}
    try:
        from app.runtime.persistence import _client
        client = _client()
        if client is None:
            return out

        cutoff = _today_start_utc_iso()

        def _fetch():
            return client.table("agent_messages").select(
                "payload, created_at"
            ).eq("agent_name", agent_name).eq("kind", "signal").gte(
                "created_at", cutoff
            ).order("created_at").execute()

        res = await asyncio.to_thread(_fetch)
        # Iterate in time order; later rows overwrite earlier so out
        # ends up holding the most-recent strategy per ticker.
        for row in (res.data or []):
            p = row.get("payload") or {}
            t = (p.get("ticker") or "").strip().upper()
            s = (p.get("strategy") or "").strip()
            if t and s:
                out[t] = s
    except Exception:  # noqa: BLE001
        pass
    return out
