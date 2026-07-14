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

    # Sector Compass bias (2026-07-13): the day's leading sector ETFs
    # ride near the front so scanners look where the market is moving.
    lead_added = 0
    for sym in list(SECTOR_BIAS.get("leaders") or [])[:3]:
        if sym not in seen and len(pool) < limit:
            seen.add(sym)
            pool.append(sym)
            lead_added += 1
    # ...and the GENERALS of those sectors (Mike 2026-07-14): the biggest
    # names of the leading industries, queued for strategy evaluation so
    # every scanner sees what the market leaders are doing.
    for g in list(SECTOR_BIAS.get("generals") or [])[:4]:
        _gsym = g.get("sym") if isinstance(g, dict) else None
        if _gsym and _gsym not in seen and len(pool) < limit:
            seen.add(_gsym)
            pool.append(_gsym)
            lead_added += 1

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
        "sector_leaders": lead_added,
        "total": len(pool),
    }
    return pool, breakdown

# --- Sector Compass (2026-07-13, Mike) --------------------------------
# The industry read on three clocks: every day the agents get the
# 3-day industry movers, Mondays add the weekly (5-day) view, and
# every ~21 days a monthly market update. ops_watchdog refreshes it
# once per day; the result lands in the activity log (Mike-visible),
# in agent memory (recallable for strategy planning), and the leading
# sector ETFs ride near the front of every scan pool so the scanners
# look where the market is actually moving.
SECTOR_ETFS: dict[str, str] = {
    "XLK": "Technology", "XLF": "Financials", "XLE": "Energy",
    "XLV": "Health Care", "XLI": "Industrials", "XLY": "Consumer Disc",
    "XLP": "Consumer Staples", "XLU": "Utilities", "XLB": "Materials",
    "XLRE": "Real Estate", "XLC": "Communications", "SMH": "Semiconductors",
    "XBI": "Biotech", "GDX": "Gold Miners",
}

# The GENERALS (Mike 2026-07-14): the biggest names of each industry --
# "see what the market industry leaders are doing so the agents can be
# prepared to enter the trades for the strategies they fit."
SECTOR_GENERALS: dict[str, list[str]] = {
    "XLK": ["AAPL", "MSFT"], "XLF": ["JPM", "V"], "XLE": ["XOM", "CVX"],
    "XLV": ["LLY", "UNH"], "XLI": ["CAT", "GE"], "XLY": ["AMZN", "HD"],
    "XLP": ["PG", "COST"], "XLU": ["NEE", "DUK"], "XLB": ["LIN", "FCX"],
    "XLRE": ["PLD", "AMT"], "XLC": ["GOOGL", "META"],
    "SMH": ["NVDA", "AVGO"], "XBI": ["VRTX", "REGN"], "GDX": ["NEM", "GOLD"],
}

# Latest compass result, module-shared. expanded_scan_pool() reads it.
SECTOR_BIAS: dict = {"as_of": "", "leaders": [], "laggards": [],
                     "generals": [], "windows": {}}


async def sector_compass() -> dict:
    """Rank the sector ETFs by 3/5/21-trading-day percent moves.

    Returns {"3d": [(sym, pct), ...ranked], "5d": ..., "21d": ...} and
    refreshes SECTOR_BIAS with the 3-day leaders/laggards. Fail-open:
    any symbol that will not fetch is simply skipped.
    """
    from app.data.candles import fetch_stock_candles
    closes: dict[str, list[float]] = {}
    for sym in SECTOR_ETFS:
        try:
            cs = await fetch_stock_candles(sym)
            if cs and len(cs) >= 22:
                closes[sym] = [float(c.close) for c in cs]
        except Exception:  # noqa: BLE001
            continue
    windows: dict[str, list] = {}
    for label, n in (("3d", 3), ("5d", 5), ("21d", 21)):
        moves = []
        for sym, cl in closes.items():
            if len(cl) > n and cl[-1 - n]:
                try:
                    moves.append(
                        (sym, round((cl[-1] / cl[-1 - n] - 1.0) * 100.0, 2)))
                except Exception:  # noqa: BLE001
                    continue
        moves.sort(key=lambda x: x[1], reverse=True)
        windows[label] = moves
    if windows.get("3d"):
        import datetime as _dt
        SECTOR_BIAS["as_of"] = _dt.datetime.now(_dt.timezone.utc).date().isoformat()
        SECTOR_BIAS["leaders"] = [s for s, _ in windows["3d"][:3]]
        SECTOR_BIAS["laggards"] = [s for s, _ in windows["3d"][-3:]]
        SECTOR_BIAS["windows"] = windows
        # Generals of the LEADING sectors: 1-day and 3-day moves, so the
        # agents know what the industry leaders are doing right now.
        gens: list[dict] = []
        for etf in SECTOR_BIAS["leaders"][:3]:
            for sym in SECTOR_GENERALS.get(etf, [])[:2]:
                try:
                    cs = await fetch_stock_candles(sym)
                    cl = [float(c.close) for c in cs] if cs else []
                    if len(cl) >= 4 and cl[-2] and cl[-4]:
                        gens.append({
                            "sym": sym, "sector": etf,
                            "d1": round((cl[-1] / cl[-2] - 1.0) * 100.0, 2),
                            "d3": round((cl[-1] / cl[-4] - 1.0) * 100.0, 2),
                        })
                except Exception:  # noqa: BLE001
                    continue
        gens.sort(key=lambda g: -g["d3"])
        SECTOR_BIAS["generals"] = gens
        windows["generals"] = gens
    return windows

