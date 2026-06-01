"""Market-wide candidate pool for the Pattern Detection scanner.

The user's watchlist is a personalisation layer, NOT the universe. The
agents see the whole market — Alpaca's session movers (gainers AND
losers, so we catch both directions) plus a curated set of sector
ETFs so the macro picture stays on every scan.

Cached for 10 minutes — the movers list barely shifts at that
granularity and it keeps Alpaca calls reasonable. Cached at module
scope, shared across users.
"""

from __future__ import annotations

import time
from typing import Optional


# Sector + index ETFs the agents should always be looking at, regardless
# of what the movers list returns. These give the macro read (SPY trend,
# sector rotation) that the per-stock scanner cannot see on its own.
SECTOR_LEADERS: list[str] = [
    "SPY",  # S&P 500
    "QQQ",  # Nasdaq-100
    "IWM",  # Russell 2000
    "DIA",  # Dow Jones
    "XLK",  # Technology
    "XLF",  # Financials
    "XLV",  # Health care
    "XLE",  # Energy
    "XLI",  # Industrials
    "XLY",  # Consumer discretionary
    "XLP",  # Consumer staples
    "XLU",  # Utilities
    "XLB",  # Materials
    "XLRE", # Real estate
]


_CACHE_TTL = 600.0  # 10 minutes
_cache: dict[str, list[str]] = {}
_cached_at: float = 0.0


async def market_wide_candidates(limit: int = 50) -> list[str]:
    """Today's broad tradeable pool beyond a user's watchlist.

    Returns up to `limit` tickers — top gainers + top losers from the
    Alpaca movers screener, padded out with sector leaders so the pool
    is never empty even when the screener returns nothing.
    """
    global _cached_at
    now = time.time()
    if _cache.get("universe") and (now - _cached_at) < _CACHE_TTL:
        return list(_cache["universe"])[:limit]

    universe: list[str] = []
    seen: set[str] = set()

    try:
        from app.brokers.alpaca_data import get_market_movers
        movers = await get_market_movers(top=30)
    except Exception:  # noqa: BLE001
        movers = {}

    # Gainers + losers both — direction-aware scanners want either.
    for side in ("gainers", "losers"):
        for entry in (movers.get(side, []) if isinstance(movers, dict) else []):
            sym = str(entry.get("symbol", "")).upper().strip()
            if not sym or sym in seen:
                continue
            seen.add(sym)
            universe.append(sym)
            if len(universe) >= limit:
                _cache["universe"] = universe
                _cached_at = now
                return list(universe)

    # Always make room for the sector / index leaders — they hold the
    # macro context the bot reasons against.
    for sym in SECTOR_LEADERS:
        if sym not in seen and len(universe) < limit:
            seen.add(sym)
            universe.append(sym)

    _cache["universe"] = universe
    _cached_at = now
    return list(universe)


async def expanded_scan_pool(watchlist_tickers: list[str],
                              limit: int = 50) -> tuple[list[str], dict]:
    """Combine the user's watchlist with the market-wide pool.

    Returns (deduplicated_pool, source_breakdown). Watchlist tickers
    come first (the user's interests lead), then the broader market
    candidates fill up to `limit`.
    """
    seen: set[str] = set()
    pool: list[str] = []
    watch_added = 0
    for t in watchlist_tickers:
        sym = (t or "").upper().strip()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        pool.append(sym)
        watch_added += 1

    extra_added = 0
    if len(pool) < limit:
        extra = await market_wide_candidates(limit=limit)
        for sym in extra:
            if sym not in seen and len(pool) < limit:
                seen.add(sym)
                pool.append(sym)
                extra_added += 1

    breakdown = {
        "watchlist": watch_added,
        "market_wide": extra_added,
        "total": len(pool),
    }
    return pool, breakdown
