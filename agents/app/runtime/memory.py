"""Agent memory — a persistent, evolving, shared knowledge store.

Phase 13. Agents pass transient messages on the bus; this gives them
something durable. An agent can `remember` an insight and `recall` it
later — across ticks and across restarts — and anything written to the
'shared' scope is readable by every other agent, so insights
cross-pollinate.

"Evolving": re-remembering the same (agent, scope, topic) does not
duplicate it — it updates the content and bumps a `weight`, so a
repeated observation grows more confident over time. Stale, low-weight
memory is pruned to keep the store bounded.

Backed by the `agent_memory` table (migration 0024). Best-effort: with
no Supabase configured, every call is a safe no-op.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

from app.config import get_settings

SHARED = "shared"
_MAX_ENTRIES = 600          # soft cap; prune() trims beyond this


def _supabase():
    s = get_settings()
    if not s.supabase_url or not s.supabase_service_role_key:
        return None
    try:
        from supabase import create_client
        return create_client(s.supabase_url, s.supabase_service_role_key)
    except Exception:  # noqa: BLE001
        return None


async def remember(agent: str, topic: str, content: str, *,
                    scope: str = SHARED, category: str = "insight",
                    weight_delta: float = 1.0) -> bool:
    """Write or reinforce a memory. Returns True on success.

    Keyed by (agent, scope, topic): a repeat updates the content and
    adds `weight_delta` to the weight rather than inserting a duplicate."""
    client = _supabase()
    if not client:
        return False
    now = datetime.now(timezone.utc).isoformat()

    def _work():
        existing = (client.table("agent_memory")
                    .select("id, weight")
                    .eq("agent", agent).eq("scope", scope).eq("topic", topic)
                    .limit(1).execute()).data or []
        if existing:
            row = existing[0]
            new_weight = float(row.get("weight") or 1.0) + weight_delta
            client.table("agent_memory").update({
                "content": content, "category": category,
                "weight": new_weight, "updated_at": now,
            }).eq("id", row["id"]).execute()
        else:
            client.table("agent_memory").insert({
                "agent": agent, "scope": scope, "topic": topic,
                "category": category, "content": content,
                "weight": 1.0, "created_at": now, "updated_at": now,
            }).execute()

    try:
        await asyncio.to_thread(_work)
        return True
    except Exception:  # noqa: BLE001
        return False


async def recall(*, agent: Optional[str] = None, scope: str = SHARED,
                  category: Optional[str] = None, limit: int = 20) -> list[dict]:
    """Read memory, most-reinforced and most-recent first. With `agent`,
    only that agent's entries in `scope`; without, all entries in `scope`."""
    client = _supabase()
    if not client:
        return []

    def _work():
        q = client.table("agent_memory").select("*").eq("scope", scope)
        if agent:
            q = q.eq("agent", agent)
        if category:
            q = q.eq("category", category)
        return (q.order("weight", desc=True)
                 .order("updated_at", desc=True)
                 .limit(limit).execute()).data or []

    try:
        return await asyncio.to_thread(_work)
    except Exception:  # noqa: BLE001
        return []


async def recall_shared(limit: int = 20) -> list[dict]:
    """Every agent's shared memory — the common knowledge pool."""
    return await recall(scope=SHARED, limit=limit)


async def prune(max_entries: int = _MAX_ENTRIES) -> int:
    """Trim the store: drop the lowest-weight, oldest entries beyond the
    cap. Returns the number removed. Best-effort."""
    client = _supabase()
    if not client:
        return 0

    def _work():
        rows = (client.table("agent_memory").select("id")
                .order("weight", desc=True).order("updated_at", desc=True)
                .execute()).data or []
        removed = 0
        for r in rows[max_entries:]:
            client.table("agent_memory").delete().eq("id", r["id"]).execute()
            removed += 1
        return removed

    try:
        return await asyncio.to_thread(_work)
    except Exception:  # noqa: BLE001
        return 0
