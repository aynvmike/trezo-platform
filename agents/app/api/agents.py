"""FastAPI router for the agent runtime.

Endpoints (full paths, no prefix — avoids the FastAPI prefix+empty-path quirk):
  GET  /agents                 — list all agents with current state
  GET  /agents/feed/recent     — recent messages across all agents
  GET  /agents/{name}/logs     — recent messages from one agent
  POST /agents/{name}/toggle   — enable/disable an agent
  POST /agents/{name}/trigger  — manually tick an agent now
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import get_settings
from app.runtime.registry import registry
from app.runtime.scheduler import _tick_agent

router = APIRouter(tags=["agents"])


class AgentInfo(BaseModel):
    name: str
    description: str
    enabled: bool
    role: str
    last_tick_at: str | None
    tick_count: int
    message_count: int
    last_error: str | None


class ToggleBody(BaseModel):
    enabled: bool


def _supabase():
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_role_key:
        return None
    try:
        from supabase import create_client

        return create_client(settings.supabase_url, settings.supabase_service_role_key)
    except Exception:
        return None


@router.get("/agents", response_model=list[AgentInfo])
async def list_agents() -> list[AgentInfo]:
    out: list[AgentInfo] = []
    for st in registry.all():
        s = st.snapshot()
        out.append(AgentInfo(**s))
    return out


# IMPORTANT: register more-specific paths BEFORE the {name} catch-all,
# otherwise '/agents/feed/recent' would match `{name}` = 'feed'.
@router.get("/agents/capabilities")
async def book_capabilities() -> dict[str, Any]:
    import asyncio
    from app.brokers.accounts import load_accounts, validation_report
    from app.runtime.capabilities import capabilities_for_book
    configured = {a.account_key: a.label for a in load_accounts()}
    client = _supabase()
    catalog_error = None
    if client:
        try:
            def _read_books():
                return client.table("trading_accounts").select("account_key,label").execute()
            result = await asyncio.to_thread(_read_books)
            for row in result.data or []:
                configured[str(row["account_key"])] = row.get("label") or str(row["account_key"])
        except Exception:
            catalog_error = "The account directory could not be read; only configured broker accounts are shown."
    else:
        catalog_error = "The account directory is unavailable; only configured broker accounts are shown."
    books = await asyncio.gather(*(capabilities_for_book(key) for key in configured))
    for book in books:
        book["label"] = configured[book["book_id"]]
    return {"books": books, "configuration_notes": validation_report(), "error": catalog_error}


@router.get("/agents/feed/recent")
async def recent_feed(limit: int = 50) -> dict[str, Any]:
    client = _supabase()
    if not client:
        raise HTTPException(status_code=503, detail="Agent activity storage is unavailable")
    try:
        res = (
            client.table("agent_messages")
            .select("*")
            .order("created_at", desc=True)
            .limit(min(max(limit, 1), 200))
            .execute()
        )
        return {"messages": res.data or []}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/agents/{name}/logs")
async def agent_logs(name: str, limit: int = 50) -> dict[str, Any]:
    st = registry.get(name)
    if not st:
        raise HTTPException(status_code=404, detail=f"Unknown agent: {name}")

    client = _supabase()
    if not client:
        raise HTTPException(status_code=503, detail="Agent activity storage is unavailable")

    try:
        res = (
            client.table("agent_messages")
            .select("*")
            .eq("agent_name", name)
            .order("created_at", desc=True)
            .limit(min(max(limit, 1), 200))
            .execute()
        )
        return {"agent": name, "messages": res.data or []}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/agents/{name}/toggle")
async def toggle_agent(name: str, body: ToggleBody) -> AgentInfo:
    st = registry.set_enabled(name, body.enabled)
    if not st:
        raise HTTPException(status_code=404, detail=f"Unknown agent: {name}")
    return AgentInfo(**st.snapshot())


@router.post("/agents/{name}/trigger")
async def trigger_agent(name: str) -> dict[str, Any]:
    st = registry.get(name)
    if not st:
        raise HTTPException(status_code=404, detail=f"Unknown agent: {name}")
    if not st.impl:
        raise HTTPException(status_code=400, detail="Agent has no implementation")

    enabled_before = st.enabled
    st.enabled = True
    try:
        await _tick_agent(st)
    finally:
        st.enabled = enabled_before

    return {
        "agent": name,
        "ticked_at": (st.last_tick_at.isoformat() if st.last_tick_at else None),
        "tick_count": st.tick_count,
        "message_count": st.message_count,
        "last_error": st.last_error,
    }
