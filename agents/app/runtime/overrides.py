"""Expert overrides - per-stock pins and disables.

Mike Phase 13a follow-up (2026-05-30). Reads `stock_strategy_overrides`
and `stock_disabled` from Supabase, prunes expired rows on every
fetch, caches the rest 30 seconds per user so per-tick reads are
cheap.

Selector calls `get_strategy_override(user_id, ticker)` to find the
pinned strategy (or None). Risk Manager calls `is_disabled(user_id,
ticker)` to veto signals on the user's disabled list.

License story: zero. Pure user input.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Optional

import structlog

from app.config import get_settings

log = structlog.get_logger("trezo.overrides")

_TTL = 30.0  # seconds - reads are cheap, no need to re-pull every tick
_overrides_cache: dict[str, tuple[dict[str, str], float]] = {}
_disabled_cache: dict[str, tuple[dict[str, str], float]] = {}


def _supabase():
    s = get_settings()
    if not s.supabase_url or not s.supabase_service_role_key:
        return None
    try:
        from supabase import create_client
        return create_client(s.supabase_url, s.supabase_service_role_key)
    except Exception:  # noqa: BLE001
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_expired(expires_at: Optional[str]) -> bool:
    if not expires_at:
        return False
    try:
        exp = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
        return exp < datetime.now(timezone.utc)
    except (TypeError, ValueError):
        return False


async def _fetch_strategy_overrides(user_id: str) -> dict[str, str]:
    """{ticker_upper: strategy} for non-expired overrides. Empty on
    error - we fail OPEN so a DB hiccup doesn't strip the user's
    overrides silently."""
    client = _supabase()
    if not client:
        return {}

    def _sync():
        return (
            client.table("stock_strategy_overrides")
            .select("ticker, strategy, expires_at")
            .eq("user_id", user_id)
            .execute()
        )
    try:
        res = await asyncio.to_thread(_sync)
        rows = res.data or []
    except Exception as e:  # noqa: BLE001
        log.warning("overrides.fetch.error", user=user_id, error=str(e))
        return {}

    out: dict[str, str] = {}
    for r in rows:
        if _is_expired(r.get("expires_at")):
            continue
        ticker = str(r.get("ticker") or "").upper()
        strategy = str(r.get("strategy") or "").strip()
        if ticker and strategy:
            out[ticker] = strategy
    return out


async def _fetch_disabled(user_id: str) -> dict[str, str]:
    """{ticker_upper: reason} for non-expired disables."""
    client = _supabase()
    if not client:
        return {}

    def _sync():
        return (
            client.table("stock_disabled")
            .select("ticker, reason, expires_at")
            .eq("user_id", user_id)
            .execute()
        )
    try:
        res = await asyncio.to_thread(_sync)
        rows = res.data or []
    except Exception as e:  # noqa: BLE001
        log.warning("overrides.disabled.error", user=user_id, error=str(e))
        return {}

    out: dict[str, str] = {}
    for r in rows:
        if _is_expired(r.get("expires_at")):
            continue
        ticker = str(r.get("ticker") or "").upper()
        reason = str(r.get("reason") or "Manually disabled in Expert overrides").strip()
        if ticker:
            out[ticker] = reason
    return out


async def get_strategy_override(user_id: Optional[str], ticker: str) -> Optional[str]:
    """The pinned strategy for (user, ticker), or None when there is
    no active override. Cached 30s per user."""
    if not user_id:
        return None
    key = str(user_id)
    now = time.time()
    hit = _overrides_cache.get(key)
    if hit is None or (now - hit[1]) > _TTL:
        fetched = await _fetch_strategy_overrides(key)
        _overrides_cache[key] = (fetched, now)
        overrides = fetched
    else:
        overrides = hit[0]
    return overrides.get(ticker.upper())


async def get_disabled_reason(user_id: Optional[str], ticker: str) -> Optional[str]:
    """Reason string when (user, ticker) is on the disabled list,
    None otherwise. Cached 30s per user."""
    if not user_id:
        return None
    key = str(user_id)
    now = time.time()
    hit = _disabled_cache.get(key)
    if hit is None or (now - hit[1]) > _TTL:
        fetched = await _fetch_disabled(key)
        _disabled_cache[key] = (fetched, now)
        disabled = fetched
    else:
        disabled = hit[0]
    return disabled.get(ticker.upper())


def invalidate_cache(user_id: Optional[str] = None):
    """Force a re-fetch on the next read. Call after the user adds /
    removes an override so the agent sees the change immediately
    instead of waiting up to 30 seconds."""
    if user_id is None:
        _overrides_cache.clear()
        _disabled_cache.clear()
    else:
        key = str(user_id)
        _overrides_cache.pop(key, None)
        _disabled_cache.pop(key, None)
