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
# REWRITTEN 2026-08-27 (audit): this used Alpha Vantage COMPANY_OVERVIEW
# on a 25-call/DAY free tier while the market-wide pool could ask for 40+
# uncached names in one build — the fallback exhausted the day's budget
# mid-build and every name after the cap silently failed to qualify.
# Now computed from the broker's corporate-actions feed (the same source
# the §4 screen trusts): trailing 12-month cash dividends / spot. No
# daily cap, split-adjusted, and cached 24h per name.
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
        from app.data.corporate_actions import (
            dividend_history, trailing_yield)
        rows = await dividend_history(t)
        if not rows:
            # [] means "no evidence" (non-payer OR feed failure — the
            # feed deliberately does not distinguish). Never cache it
            # and never call it 0.0: the consumer skips the name, and a
            # transient failure gets to retry next build.
            return None
        from app.data.candles import fetch_stock_candles
        cs = await fetch_stock_candles(t)
        spot = float(cs[-1].close) if cs else 0.0
        if spot <= 0:
            return None
        v = trailing_yield(rows, spot)
        if v is None:
            return None
        _yield_cache[t] = (float(v), now)
        return float(v)
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
    # Tier drives lane rule #4 (GROWTH names never wear a covered call).
    # 'UNKNOWN' for legacy sources that predate the §4 screen — callers
    # must treat UNKNOWN as not-call-eligible, same as UNVERIFIED.
    tier: str = "UNKNOWN"


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

    # 1) Seed list (always present). NOTE on ordering (audit 2026-08-27):
    # a per-seed rotation used to live here, but `seen` is a dict handed
    # to _ordered(), which re-sorts and rotates the WHOLE bench at the
    # end — so any slicing done here was dead code the moment _ordered()
    # shipped (2026-08-25). Rotation lives in _ordered() and only there.
    seen: dict[str, WheelCandidate] = {}
    for sym in WHEEL_WATCHLIST:
        y = DIVIDEND_YIELDS.get(sym, 0.02)
        seen[sym] = WheelCandidate(ticker=sym, source="seed", yield_pct=y)

    # 1b) MARKET-SCAN additions (Mike 2026-07-16: "expand it further --
    # I do not want to limit... scan a few industry winners as well").
    # The leading sectors' generals and the day's most-actives join the
    # bench when their CSP collateral could actually FIT this account
    # (strike ~5% under spot -> reserve = strike x 100 <= the growth
    # allowance, 25% of equity). No dividend gate here: evaluate_csp
    # judges the premium on merit; source='market' shows provenance.
    try:
        from app.data.market_universe import (
            SECTOR_BIAS, market_wide_candidates,
        )
        market_names: list[str] = []
        for g in (SECTOR_BIAS.get("generals") or []):
            _s = str(g.get("sym") or "").upper()
            if _s:
                market_names.append(_s)
        try:
            _movers = await market_wide_candidates(limit=20)
            market_names.extend(str(m).upper() for m in (_movers or []))
        except Exception:  # noqa: BLE001
            pass
        _ceiling = 0.0
        try:
            from app.paper.allocation import effective_equity
            _eq = await effective_equity(user_id) if user_id else 0.0
            _ceiling = ((_eq * 0.25) / 100.0) / 0.95 if _eq > 0 else 0.0
        except Exception:  # noqa: BLE001
            _ceiling = 0.0
        _added = 0
        for _sym in market_names:
            if not _sym or _sym in seen or _added >= 15:
                continue
            if _ceiling > 0:
                try:
                    from app.data.candles import fetch_stock_candles
                    _cs = await fetch_stock_candles(_sym)
                    _spot = float(_cs[-1].close) if _cs else 0.0
                except Exception:  # noqa: BLE001
                    _spot = 0.0
                if _spot <= 0 or _spot > _ceiling:
                    continue
            seen[_sym] = WheelCandidate(
                ticker=_sym, source="market_wide",
                yield_pct=DIVIDEND_YIELDS.get(_sym, 0.0))
            _added += 1
    except Exception:  # noqa: BLE001
        pass

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
    #    so the Wheel's ceiling tracks the stock side automatically.
    #
    #    THE GATE (rewritten 2026-08-22, Mike: "analyze it for market wide
    #    and not a default list only"). The pool was already market-wide;
    #    the GATE was not, and the gate is what decides. It asked a
    #    40-name dict, then fell back to Alpha Vantage with a budget of
    #    FIVE calls per build against a 25-per-DAY tier — so any name we
    #    had not pre-listed effectively could not qualify, and the
    #    market-wide pool collapsed back to the curated list every tick.
    #
    #    Now: the §4 entry screen (dividend_screen) judges ANY ticker on
    #    Finnhub fundamentals — payout ratio, raise streak, cut history —
    #    at 60 calls/MINUTE, with results cached in Supabase for a week.
    #    The covered universe therefore RATCHETS: every name screened
    #    once is free thereafter, so coverage grows toward the whole
    #    market instead of resetting. Names the screen cannot verify are
    #    skipped, not admitted — silence is not consent.
    try:
        from app.data.market_universe import market_wide_candidates as _stock_pool
        from app.strategies.dividend_screen import screen_many

        _pool = [s.upper().strip() for s in await _stock_pool(limit=80)]
        _unseen = [s for s in _pool if s and s not in seen]
        _verdicts = await screen_many(_unseen)
        for sym, verdict in _verdicts.items():
            # Ladder-eligible admits BOTH tiers into the universe; the
            # GROWTH/HIGH_YIELD split decides what may be DONE with a
            # name (lane rule #4), not whether the lane may hold it.
            if not verdict.ladder_eligible:
                continue
            seen[sym] = WheelCandidate(
                ticker=sym, source="market_wide",
                yield_pct=verdict.yield_pct or 0.0,
                tier=verdict.tier,
            )
    except Exception as e:  # noqa: BLE001
        log.warning("wheel_universe.stock_pool_failed", error=str(e)[:200])

    universe = _ordered(list(seen.values()))
    _cache[user_id] = (universe, now)
    return universe


def _ordered(cands: list, ordinal: Optional[int] = None) -> list:
    """Positions first; everything else on ONE rotating bench.

    WHY (2026-08-25, Mike: "the options are looking quite the same
    market pool as before, a lot of Ford and AGNC"). The old sort was
    (position, seed, ticker) -- which did two bad things at once:

      1. The 22-name curated seed permanently outranked every
         market-wide candidate, so the names Task #5 added "to be more
         open to the markets" sorted LAST and, with 1-3 CSP slots,
         were never reached. Market-wide in the pool, whitelist in
         effect -- the same costume the 08-22 audit caught elsewhere.
      2. Sorting by ticker WITHIN the seed group silently undid the
         2026-07-16 seed rotation. That fix shipped, worked, and was
         then re-alphabetized to death by this line: with cheap names
         winning the affordability check, alphabetical order made
         AGNC (~$9) the permanent front of the queue, with F close
         behind. Exactly the two names Mike noticed.

    Now: open positions keep priority (they carry obligations), and
    the ENTIRE remaining bench -- seed, watchlist and market-wide
    together -- rotates by calendar day, so every affordable name gets
    its turn at the head regardless of which list it came from or what
    letter it starts with.
    """
    if ordinal is None:
        from datetime import date as _d
        ordinal = _d.today().toordinal()
    positions = sorted((c for c in cands if c.source == "position"),
                       key=lambda c: c.ticker)
    bench = sorted((c for c in cands if c.source != "position"),
                   key=lambda c: c.ticker)
    if bench:
        r = int(ordinal) % len(bench)
        bench = bench[r:] + bench[:r]
    return positions + bench


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
