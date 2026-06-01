"""STMS — Small Trades Momentum Strategy.

Spec (from TREZO_STRATEGY_RULES.md §1):
  - Trading window: 7:00 AM – 11:00 AM ET
  - Stock price: $1.00 – $20.00
  - Daily move already +10% on the day
  - Relative volume: 5x average minimum
  - Catalyst: recent company news feeds the score's catalyst factor
  - Float < 20M shares (shares-outstanding proxy, Finnhub /stock/profile2)
  - Continuation setup: a pole + shallow-pullback (bull-flag family)
    structural check on the available daily candles
  - TCS 750+ threshold

Position sizing:
  - Risk per trade: 5% of stock account
  - Stop: 5% below entry
  - Target: 10% above entry (50% of position), trailing stop on the rest

This module exposes pure helpers + the founder's seed STMS watchlist.
The actual scanning loop lives in `app/agents/stms_scanner.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional

from app.patterns import Candle


# ---- Seed watchlist (from TREZO_FOUNDER_WATCHLIST.md "PENNY STOCK STMS POOL") --
SEED_WATCHLIST: list[str] = [
    "STAFQ", "NVIVQ", "ZSANQ", "XWEL", "ZNB",
    "JAGX", "SDIG", "GSAT", "ACHR",
    # Additional small caps known for morning volatility
    "SOUN", "RIVN", "PLTR", "BB", "AMC",
]


# ---- Configurable thresholds ----------------------------------------------
TCS_THRESHOLD       = 750
PRICE_MIN           = 1.00
PRICE_MAX           = 20.00
DAILY_MOVE_MIN_PCT  = 10.0   # already up 10%+
RELATIVE_VOLUME_MIN = 5.0    # 5x average
FLOAT_MAX_MILLIONS  = 20.0   # small-float screen: under 20M shares


# ---- Time window check ----------------------------------------------------


def is_trading_window(now: Optional[datetime] = None) -> bool:
    """STMS trades 7-11 AM US Eastern, weekdays only.

    Naive approximation using UTC: 7-11 AM ET = 11:00-15:00 UTC in EST,
    12:00-16:00 UTC in EDT. We accept the slightly-wider 11:00-15:30 UTC
    window so DST transitions don't surprise us. Phase 6c can do proper
    timezone-aware handling with `zoneinfo`.
    """
    now = now or datetime.now(timezone.utc)
    if now.weekday() >= 5:        # Sat=5, Sun=6
        return False
    h = now.hour + now.minute / 60.0
    return 11.0 <= h <= 16.0


# ---- Candidate evaluation -------------------------------------------------


@dataclass
class StmsCandidate:
    ticker: str
    price: float
    daily_move_pct: float
    relative_volume: float
    passes_price: bool
    passes_move: bool
    passes_volume: bool


def evaluate_candidate(ticker: str, candles: list[Candle]) -> Optional[StmsCandidate]:
    """Check whether `ticker` meets the STMS entry-filter criteria.

    Returns a `StmsCandidate` even when one or two filters fail — caller
    decides whether to require all-pass. Returns None when there isn't
    enough candle data to evaluate.
    """
    if not candles or len(candles) < 21:
        return None

    last = candles[-1]
    prior_close = candles[-2].close if len(candles) >= 2 else last.open
    if prior_close <= 0:
        return None

    price = float(last.close)
    daily_move_pct = (price - prior_close) / prior_close * 100.0

    # Relative volume vs 20-day average (excluding today)
    vols = [c.volume for c in candles[-21:-1] if c.volume > 0]
    avg_vol = (sum(vols) / len(vols)) if vols else 0.0
    relative_volume = (last.volume / avg_vol) if avg_vol > 0 else 0.0

    passes_price  = PRICE_MIN <= price <= PRICE_MAX
    passes_move   = daily_move_pct >= DAILY_MOVE_MIN_PCT
    passes_volume = relative_volume >= RELATIVE_VOLUME_MIN

    return StmsCandidate(
        ticker=ticker,
        price=price,
        daily_move_pct=daily_move_pct,
        relative_volume=relative_volume,
        passes_price=passes_price,
        passes_move=passes_move,
        passes_volume=passes_volume,
    )


def all_filters_pass(c: StmsCandidate) -> bool:
    """The three candle-only entry filters pass: price, daily move,
    relative volume.

    Float, catalyst, and chart-pattern checks need async data fetches,
    so they are applied separately in the STMS scanner — float via
    shares_outstanding_millions, catalyst via fetch_company_news, and
    the continuation setup via stms_chart_setup below.
    """
    return c.passes_price and c.passes_move and c.passes_volume


def stms_chart_setup(candles: list[Candle]) -> bool:
    """A continuation-setup check for STMS - a strong recent run-up (the
    'pole') followed by a shallow pullback or tight consolidation (the
    'flag' / micro-pullback).

    This is a structural read of the bull-flag family on the available
    daily candles. A precise intraday Bull Flag / Flat Top / Micro-
    Pullback detector would need an intraday feed and stays a deeper
    follow-up.
    """
    if len(candles) < 12:
        return False
    window = candles[-10:-2]                 # the run-up window (the 'pole')
    if not window:
        return False
    pole_low = min(float(c.low) for c in window)
    pole_high = max(float(c.high) for c in window)
    if pole_low <= 0 or pole_high <= 0:
        return False
    pole_gain = (pole_high - pole_low) / pole_low
    if pole_gain < 0.12:                     # need a real run to consolidate from
        return False
    last = float(candles[-1].close)
    recent_low = min(float(c.low) for c in candles[-2:])
    pullback = (pole_high - last) / pole_high
    midpoint = (pole_high + pole_low) / 2.0
    # A shallow pullback that holds above the pole's midpoint reads as a
    # flag/consolidation; a deep drop below it reads as a breakdown.
    return -0.02 <= pullback <= 0.15 and recent_low >= midpoint


# ---- Dynamic watchlist (Phase 12 follow-up) --------------------------------


async def dynamic_watchlist(fallback: bool = True) -> list[str]:
    """Today's STMS hunting ground.

    STMS is meant to trade "stocks in motion", not a fixed list. This pulls
    Alpaca's top gainers for the session and keeps the ones inside the STMS
    price band ($1-$20) — the small, fast movers the strategy is built for.
    Falls back to SEED_WATCHLIST when the movers feed is empty or the keys
    are not configured, so the scanner always has something to scan.
    """
    try:
        from app.brokers.alpaca_data import get_market_movers
        movers = await get_market_movers(top=40)
    except Exception:  # noqa: BLE001
        movers = {}

    gainers = movers.get("gainers", []) if isinstance(movers, dict) else []
    seen: set[str] = set()
    universe: list[str] = []
    for g in gainers:
        sym = str(g.get("symbol", "")).upper().strip()
        price = 0.0
        try:
            price = float(g.get("price") or 0)
        except (TypeError, ValueError):
            price = 0.0
        if sym and sym not in seen and PRICE_MIN <= price <= PRICE_MAX:
            seen.add(sym)
            universe.append(sym)

    if universe:
        return universe
    return list(SEED_WATCHLIST) if fallback else []
