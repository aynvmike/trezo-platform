"""Async persistence of agent messages to Supabase (best-effort)."""

from __future__ import annotations

import asyncio
from typing import Optional

from app.agents.base import AgentMessage
from app.config import get_settings


_supabase = None  # lazy


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


async def persist_message(message: AgentMessage, user_id: Optional[str] = None) -> None:
    """Best-effort write. Failures are swallowed so the bus keeps moving."""
    client = _client()
    if not client:
        return

    def _sync():
        try:
            client.table("agent_messages").insert({
                "user_id": user_id,
                "agent_name": message.agent,
                "kind": message.kind,
                "confidence": message.confidence,
                "payload": message.payload,
            }).execute()
        except Exception as e:  # noqa: BLE001
            print(f"[persistence] insert failed: {e}")

    await asyncio.to_thread(_sync)
