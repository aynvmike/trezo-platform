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

    def _clean(sym: str) -> bool:
        # Drop warrants/units/odd share classes ("KRSP.WS", "ABC-U") --
        # they wasted scan slots and always died at the gates (2026-07-02).
        return sym.isalpha() and 1 <= len(sym) <= 5

    try:
        from app.brokers.alpaca_data import get_market_movers, get_most_actives
        movers = await get_market_movers(top=30)
    except Exception:  # noqa: BLE001
        movers = {}
        get_most_actives = None  # type: ignore[assignment]

    # Rotating-slice universe (Mike 2026-07-08: "I see the same stocks
    # keep getting triggered -- use more of the market"). Pull a DEEP
    # most-actives list (top 60) and keep the head PLUS an hour-rotating
    # window from the tail, so different liquid names cycle through the
    # pool all day instead of the same leaders every scan.
    actives: list[str] = []
    if get_most_actives is not None:
        try:
            _deep = [s for s in await get_most_actives(top=60) if _clean(s)]
            _head, _tail = _deep[:12], _deep[12:]
            if _tail:
                import time as _t
                _off = (int(_t.time() // 3600)) % max(len(_tail), 1)
                _rot = (_tail[_off:] + _tail[:_off])[:13]
            else:
                _rot = []
            actives = _head + _rot
        except Exception:  # noqa: BLE001
            actives = []

    gainers: list[str] = []
    losers: list[str] = []
    junk_skipped = 0
    for side, dest in (("gainers", gainers), ("losers", losers)):
        for entry in (movers.get(side, []) if isinstance(movers, dict) else []):
            sym = str(entry.get("symbol", "")).upper().strip()
            if not sym:
                continue
            if not _clean(sym):
                junk_skipped += 1
                continue
            dest.append(sym)

    # Interleave: most-actives first (liquid, scalp-friendly), then
    # gainers/losers round-robin so both directions stay represented.
    lists = [actives, gainers, losers]
    i = 0
    while len(universe) < limit and any(lists):
        src_list = lists[i % 3]
        i += 1
        if not src_list:
            continue
        sym = src_list.pop(0)
        if sym in seen:
            continue
        seen.add(sym)
        universe.append(sym)

    # Always make room for the sector / index leaders — they hold the
    # macro context the bot reasons against.
    for sym in SECTOR_LEADERS:
        if sym not in seen and len(universe) < limit:
            seen.add(sym)
            universe.append(sym)

    # Visibility (2026-07-02): one line per refresh showing what the
    # market handed the scanners.
    try:
        from app.agents.activity_log import record as _arec
        _arec("scan_pool_refresh", "MARKET",
              reason=(f"{len([s for s in universe if s not in SECTOR_LEADERS])} "
                      f"market names ({i and 'actives+gainers+losers' or 'none'}), "
                      f"{junk_skipped} junk symbols skipped"),
              extra={"pool_size": len(universe)})
    except Exception:  # noqa: BLE001
        pass

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
