"""Wheel candidate-universe builder.

Mike 2026-06-01: the curated WHEEL_WATCHLIST is a starter, not a
hardcoded cage. The bot should be able to consider ANY quality
dividend stock the user has surfaced via watchlists. This module is
the single source of truth for "what symbols can the Wheel work on
right now" - the Options Scanner imports `get_wheel_universe(user)`
instead of iterating the static list.

Composition (in priority order; #5 added 2026-06-11, Task #6 --
the Wheel's candidate ceiling is the same market-wide pool the stock
agents scan, gated by dividend quality, never a curated whitelist):
  1. Curated seed (`WHEEL_WATCHLIST`) - always included. The 17 names
     we picked for their tier-balanced economics. Source = strategy.
  2. User watchlists - every stock-type ticker in any of the user's
     watchlists whose name signals "dividend" or "income" or
     "wheel" or "yieldmax" or that's in our known-dividend yield
     table. Source = watchlist.
  3. Active option positions - whatever the user already holds an
     options position on. The Wheel should keep working those
     positions even if they fall out of (1) and (2). Source =
     position.

Quality gate (applied to additions from #2):
  - Must have a known dividend yield > 1.5% (uses the wheel.py
    DIVIDEND_YIELDS table). Names we don't know default to skip
    rather than auto-include - the Wheel works best on names we've
    tagged a yield for.
  - Not currently in a different layer's active cycle (e.g. don't
    wheel a name the Stock Bot is actively swinging).

Cached 30s per user_id so the scanner's 30-min tick is cheap.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Optional

import structlog

from app.config import get_settings
from app.strategies.wheel import WHEEL_WATCHLIST

log = structlog.get_logger("trezo.wheel_universe")

# Dividend yields we know for the curated seed (and a small extension
# for names commonly added). Anything else falls back to the
# qualification check via FINNHUB / watchlist tags. Imported by
# `web/src/app/dashboard/wheel/page.tsx` indirectly via API.
DIVIDEND_YIELDS: dict[str, float] = {
    # Tier A
    "O": 0.055, "MAIN": 0.060, "STAG": 0.045, "NLY": 0.130, "ARCC": 0.090,
    # Tier B
    "F": 0.060, "T": 0.065, "KMI": 0.060, "VZ": 0.065, "MO": 0.080,
    "INTC": 0.015,
    # Tier C
    "PFE": 0.060, "KHC": 0.050, "CSCO": 0.030, "BMY": 0.045, "KEY": 0.050,
    "HPQ": 0.030,
    # Common adds that pass the gate when surfaced via watchlists
    "JNJ": 0.029, "PG": 0.024, "KO": 0.030, "WMT": 0.012, "JPM": 0.025,
    "BAC": 0.030, "XOM": 0.035, "CVX": 0.040, "ABBV": 0.045, "MRK": 0.030,
    "IBM": 0.045, "DOW": 0.060, "MMM": 0.060, "TGT": 0.040, "PEP": 0.030,
}

MIN_QUALIFYING_YIELD = 0.015   # 1.5%. Names below this are not wheel-y enough.


# Task #5 (2026-06-10, Mike's ask: "options be more open to the markets
# and different industries like the stock agents"). Market-wide pool
# of liquid dividend payers across sectors. Same role as
# expanded_scan_pool() does for Pattern Detection - it gives the Wheel
# a broader candidate set without forcing Mike to add each name to a
# watchlist. Names here still go through the same yield-quality gate.
MARKET_WIDE_DIVIDEND_POOL = [
    # Mega-cap consumer staples
    "PG", "KO", "PEP", "MDLZ", "CL", "KMB", "GIS", "K",
    # Healthcare blue-chip yielders
    "JNJ", "ABBV", "PFE", "MRK", "BMY", "AMGN", "GILD", "LLY",
    # Banks + REITs
    "JPM", "BAC", "C", "WFC", "USB", "PNC", "TFC",
    "SPG", "O", "AMT", "PLD", "WELL", "VTR",
    # Energy + utilities
    "XOM", "CVX", "COP", "PSX", "VLO", "MPC",
    "NEE", "DUK", "SO", "AEP", "EXC", "D",
    # Industrials + materials
    "MMM", "CAT", "DE", "HON", "GE", "DOW",
    # Tech yielders + telcos
    "IBM", "CSCO", "INTC", "ORCL", "QCOM", "TXN",
    "T", "VZ", "TMUS",
    # ETF dividend baskets (Wheel-friendly liquidity)
    "SCHD", "VYM", "DVY", "HDV", "NOBL", "JEPI", "JEPQ", "DGRO",
]


async def market_wide_dividend_candidates() -> list[str]:
    """Return the market-wide dividend pool. Static for now; future
    versions can pull from S&P Dividend Aristocrats live or scrape
    high-yield ETF constituents. Returns deduplicated upper-case
    tickers."""
    return [t.strip().upper() for t in MARKET_WIDE_DIVIDEND_POOL if t.strip()]


# Task #49 (2026-06-05): live yield lookup for names not in DIVIDEND_YIELDS.
# Uses Alpha Vantage COMPANY_OVERVIEW when an AV key is configured;
# results cached for 24h to stay under the 25/day free tier. Falls back
# to None on any failure -> consumer treats as ineligible.
import time
_yield_cache: dict[str, tuple[float, float]] = {}  # ticker -> (yield_pct, fetched_at)
_YIELD_CACHE_TTL = 86400  # 24h


async def _yield_live_lookup(ticker: str) -> Optional[float]:
    t = ticker.upper().strip()
    now = time.time()
    hit = _yield_cache.get(t)
    if hit and (now - hit[1]) < _YIELD_CACHE_TTL:
        return hit[0]
    try:
        from app.config import get_settings as _gs_yield
        key = (getattr(_gs_yield(), "alpha_vantage_api_key", "") or "").strip()
        if not key:
            return None
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                "https://www.alphavantage.co/query",
                params={"function": "COMPANY_OVERVIEW", "symbol": t, "apikey": key},
            )
            if r.status_code != 200:
                return None
            data = r.json()
            div_yield = data.get("DividendYield")
            if div_yield in (None, "", "None"):
                _yield_cache[t] = (0.0, now)
                return 0.0
            v = float(div_yield)
            _yield_cache[t] = (v, now)
            return v
    except Exception:  # noqa: BLE001
        return None


async def yield_for(ticker: str) -> Optional[float]:
    """Get the dividend yield for a ticker. Prefers the static dict
    (fast, known-good). Falls back to live lookup. Returns None when
    we genuinely can't say."""
    t = ticker.upper().strip()
    if t in DIVIDEND_YIELDS:
        return DIVIDEND_YIELDS[t]
    return await _yield_live_lookup(t)
_CACHE_TTL_SECONDS = 30


@dataclass
class WheelCandidate:
    """A single ticker the Wheel is allowed to consider, with the
    reason it qualified. The UI can use `source` to render reason chips."""
    ticker: str
    source: str        # 'seed' | 'watchlist' | 'position' | 'market_wide'
    yield_pct: float


# Per-user cache: user_id -> (candidates, fetched_at)
_cache: dict[Optional[str], tuple[list[WheelCandidate], float]] = {}


def _supabase():
    s = get_settings()
    if not s.supabase_url or not s.supabase_service_role_key:
        return None
    try:
        from supabase import create_client
        return create_client(s.supabase_url, s.supabase_service_role_key)
    except Exception:  # noqa: BLE001
        return None


def _looks_dividend_friendly(name: str) -> bool:
    """Heuristic: is this watchlist's NAME a hint that its tickers
    should be considered for the Wheel? Dividend / income / yield /
    wheel / yieldmax all qualify; "growth" or "tech" do not."""
    n = (name or "").lower()
    return any(k in n for k in (
        "dividend", "income", "yield", "wheel", "yieldmax",
        "rex", "schd", "jepi", "jepq", "reit",
    ))


async def get_wheel_universe(user_id: Optional[str]) -> list[WheelCandidate]:
    """Build the full set of candidates the Wheel may scan for this
    user. Cached 30s. Never raises - on any data failure, falls back
    to the seed list alone (safe default)."""
    now = time.time()
    hit = _cache.get(user_id)
    if hit and (now - hit[1]) < _CACHE_TTL_SECONDS:
        return hit[0]

    # 1) Seed list (always present). Rotated by the calendar day
    # (Mike 2026-07-16): the scan used to walk the list in a FIXED
    # order, so with one CSP slot the first affordable name (F) won
    # every single cycle. Rotation gives every affordable name a turn.
    from datetime import date as _rot_d
    _seed = list(WHEEL_WATCHLIST)
    if _seed:
        _r = _rot_d.today().toordinal() % len(_seed)
        _seed = _seed[_r:] + _seed[:_r]
    seen: dict[str, WheelCandidate] = {}
    for sym in _seed:
        y = DIVIDEND_YIELDS.get(sym, 0.02)
        seen[sym] = WheelCandidate(ticker=sym, source="seed", yield_pct=y)

    # 2) Watchlist additions (only when we have a user_id and Supabase)
    client = _supabase()
    if client and user_id:
        try:
            wl_rows, item_rows = await asyncio.to_thread(
                _fetch_watchlist_tickers, client, user_id,
            )
            for wl in wl_rows:
                wl_id = wl["id"]
                wl_name = wl["name"]
                if not _looks_dividend_friendly(wl_name):
                    continue
                for item in item_rows:
                    if item["watchlist_id"] != wl_id:
                        continue
                    sym = (item.get("ticker") or "").upper().strip()
                    if not sym or sym in seen:
                        continue
                    if (item.get("asset_type") or "stock") != "stock":
                        continue
                    y = DIVIDEND_YIELDS.get(sym, 0.0)
                    if y < MIN_QUALIFYING_YIELD:
                        continue
                    seen[sym] = WheelCandidate(
                        ticker=sym, source="watchlist", yield_pct=y,
                    )
        except Exception as e:  # noqa: BLE001
            log.warning("wheel_universe.watchlist_fetch_failed",
                        user_id=user_id, error=str(e)[:200])

    # 3) Active option positions (keep working what's already open)
    if client and user_id:
        try:
            pos_rows = await asyncio.to_thread(
                _fetch_active_underlyings, client, user_id,
            )
            for sym in pos_rows:
                sym = sym.upper().strip()
                if not sym or sym in seen:
                    continue
                y = DIVIDEND_YIELDS.get(sym, 0.02)
                seen[sym] = WheelCandidate(
                    ticker=sym, source="position", yield_pct=y,
                )
        except Exception as e:  # noqa: BLE001
            log.warning("wheel_universe.position_fetch_failed",
                        user_id=user_id, error=str(e)[:200])

    # 4) Market-wide dividend pool (Task #5, Mike 2026-06-10:
    #    "options be more open to the markets and different
    #    industries like the stock agents"). Same yield gate as
    #    watchlist additions - we don't auto-include names whose
    #    yield we genuinely don't know.
    try:
        for sym in await market_wide_dividend_candidates():
            if sym in seen:
                continue
            y = DIVIDEND_YIELDS.get(sym)
            if y is None:
                # Try live lookup - if still no yield, skip.
                y = await yield_for(sym)
            if y is None or y < MIN_QUALIFYING_YIELD:
                continue
            seen[sym] = WheelCandidate(
                ticker=sym, source="market_wide", yield_pct=y,
            )
    except Exception as e:  # noqa: BLE001
        log.warning("wheel_universe.market_wide_failed", error=str(e)[:200])

    # 5) Full stock-side market pool (Task #6, Mike 2026-06-10: "they
    #    should all be able to see all the stocks not a limited few").
    #    This is the SAME dynamic universe Pattern Detection scans
    #    (Alpaca movers, gainers + losers, padded with sector leaders),
    #    so the Wheel's ceiling now tracks the stock side automatically
    #    instead of stopping at the curated 64-name pool. Every name
    #    still passes the same dividend-yield quality gate -- the gate
    #    decides wheel-worthiness, the pool is no longer the cage.
    #    Live AV yield lookups are budgeted per build to protect the
    #    25/day free tier; unknown names simply wait for a later tick.
    try:
        from app.data.market_universe import market_wide_candidates as _stock_pool
        live_budget = 5
        for sym in await _stock_pool(limit=50):
            sym = sym.upper().strip()
            if not sym or sym in seen:
                continue
            y = DIVIDEND_YIELDS.get(sym)
            if y is None:
                if live_budget <= 0:
                    continue
                live_budget -= 1
                y = await yield_for(sym)
            if y is None or y < MIN_QUALIFYING_YIELD:
                continue
            seen[sym] = WheelCandidate(
                ticker=sym, source="market_wide", yield_pct=y,
            )
    except Exception as e:  # noqa: BLE001
        log.warning("wheel_universe.stock_pool_failed", error=str(e)[:200])

    universe = sorted(seen.values(), key=lambda c: (c.source != "position",
                                                    c.source != "seed",
                                                    c.ticker))
    _cache[user_id] = (universe, now)
    return universe


def _fetch_watchlist_tickers(client, user_id: str):
    """Synchronous Supabase fetch helper for asyncio.to_thread."""
    wl_res = (
        client.table("watchlists")
        .select("id, name")
        .eq("user_id", user_id)
        .execute()
    )
    wl_rows = wl_res.data or []
    if not wl_rows:
        return [], []
    wl_ids = [r["id"] for r in wl_rows]
    item_res = (
        client.table("watchlist_items")
        .select("watchlist_id, ticker, asset_type")
        .in_("watchlist_id", wl_ids)
        .execute()
    )
    return wl_rows, (item_res.data or [])


def _fetch_active_underlyings(client, user_id: str) -> list[str]:
    """Distinct underlyings the user has open options positions on.
    Includes wheel_csp + wheel_cc + any directional plays so we don't
    surprise-close anything by dropping a name from the universe."""
    res = (
        client.table("options_positions")
        .select("underlying")
        .eq("user_id", user_id)
        .eq("status", "open")
        .execute()
    )
    return list({(r.get("underlying") or "").upper() for r in (res.data or [])})


def invalidate_cache(user_id: Optional[str] = None) -> None:
    """Drop the cached universe for a user (or globally). Called by
    the watchlist mutation API so adding a name shows up immediately."""
    if user_id is None:
        _cache.clear()
    else:
        _cache.pop(user_id, None)
