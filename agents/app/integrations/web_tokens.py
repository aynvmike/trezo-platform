"""Per-user broker-token lookups — agents-side client of the web's
internal /api/internal/broker-token endpoint.

Why this exists: Trezo's Connections page (OAuth) stores each user's
broker access token encrypted in the database. Only the web service
holds the decryption key. Agents call this helper at execute time to
fetch a per-user token; the web returns plaintext, agents pass it
through to the broker call, then drop it.

Falls back gracefully — when the endpoint is unreachable, the user
has no connection, or the shared secret is misconfigured, this
returns None and the caller falls back to the env-driven keys. That
lets the legacy single-tenant setup keep working through the
transition.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class BrokerToken:
    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[str] = None
    broker: Optional[str] = None


_CACHE_TTL = 120.0  # seconds — long enough to avoid hammering, short
                    # enough that a fresh OAuth revoke takes effect quickly.
_cache: dict[tuple[str, str], tuple[BrokerToken, float]] = {}


def _web_base() -> str:
    # Where the web service listens. Used to call /api/internal/...
    return (os.environ.get("WEB_INTERNAL_BASE_URL")
            or os.environ.get("NEXT_PUBLIC_BASE_URL")
            or "http://localhost:3000").rstrip("/")


def _shared_secret() -> Optional[str]:
    return os.environ.get("AGENTS_SHARED_SECRET")


async def get_user_broker_token(user_id: str, broker: str) -> Optional[BrokerToken]:
    """Return the user's active broker token, or None if not connected.

    Cached for 2 minutes per (user, broker) tuple so a single trade
    flurry doesn't make 50 round-trips."""
    if not user_id or not broker:
        return None
    secret = _shared_secret()
    if not secret:
        return None  # legacy mode — caller falls back to env keys

    key = (user_id, broker)
    now = time.time()
    hit = _cache.get(key)
    if hit is not None and (now - hit[1]) < _CACHE_TTL:
        return hit[0]

    try:
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{_web_base()}/api/internal/broker-token",
                headers={
                    "Authorization": f"Bearer {secret}",
                    "Content-Type": "application/json",
                },
                json={"user_id": user_id, "broker": broker},
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
    except Exception:  # noqa: BLE001
        return None

    tok = BrokerToken(
        access_token=str(data.get("access_token") or ""),
        refresh_token=(data.get("refresh_token") or None),
        expires_at=(data.get("expires_at") or None),
        broker=str(data.get("broker") or broker),
    )
    if not tok.access_token:
        return None
    _cache[key] = (tok, now)
    return tok


def invalidate_user_token(user_id: str, broker: str) -> None:
    """Drop the cached token (call after a 401 from the broker so the
    next attempt re-fetches)."""
    _cache.pop((user_id, broker), None)
