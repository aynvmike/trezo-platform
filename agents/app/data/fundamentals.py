"""Company fundamentals — Finnhub /stock/profile2.

Data feed, Part 3. Provides the share-float proxy the STMS strategy
needs for its small-float filter. Best-effort: returns None when there
is no key, the endpoint is gated, or anything fails — so the scanner
keeps working on its other filters. Cached for the process lifetime,
since share counts barely move day to day.
"""

from __future__ import annotations

from typing import Optional

from app.config import get_settings

FINNHUB_PROFILE_URL = "https://finnhub.io/api/v1/stock/profile2"

# symbol -> shares outstanding in millions (process-lifetime cache)
_cache: dict[str, float] = {}


async def shares_outstanding_millions(symbol: str) -> Optional[float]:
    """Shares outstanding for `symbol`, in millions. None if unavailable.

    A free-tier proxy for share float — close enough for the STMS
    small-float screen on micro-caps.
    """
    sym = (symbol or "").upper()
    if not sym:
        return None
    if sym in _cache:
        return _cache[sym]
    key = get_settings().finnhub_api_key
    if not key:
        return None
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(FINNHUB_PROFILE_URL,
                                    params={"symbol": sym, "token": key})
            resp.raise_for_status()
            data = resp.json()
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(data, dict):
        return None
    try:
        val = float(data.get("shareOutstanding"))
    except (TypeError, ValueError):
        return None
    if val <= 0:
        return None
    _cache[sym] = val
    return val
