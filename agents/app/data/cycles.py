"""Cycle data - earnings calendar + ex-dividend calendar.

Mike's "the bot should think like a human" Phase 13 push (2026-05-30).
Pulls upcoming earnings and ex-div dates per ticker from Finnhub, so
agents can reason about WHERE in the cycle a stock currently sits -
not just its TCS score.

License: Finnhub free tier permits commercial use with attribution.
Trezo already uses Finnhub for fundamentals; no new license dance.

Endpoints:
  /calendar/earnings?from=YYYY-MM-DD&to=YYYY-MM-DD&symbol=XXX
  /calendar/dividend?from=YYYY-MM-DD&to=YYYY-MM-DD&symbol=XXX

Cached 24h: both calendars change at most daily.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
import structlog

from app.config import get_settings

log = structlog.get_logger("trezo.data.cycles")

_BASE = "https://finnhub.io/api/v1"
_CACHE_TTL = 24 * 60 * 60  # 24 hours - cycles update daily at most


@dataclass
class CyclePosition:
    """Where a stock sits in its earnings + dividend cycles RIGHT NOW.

    All "days_until" fields are signed:
      - positive: event is in the future
      - 0: event is today
      - negative: event has passed (within lookback window)
      - None: no event found in the lookback / lookahead window

    `iv_environment` is the simple human read:
      - "high" : within 7 days BEFORE earnings (IV crush opportunity)
      - "post_earnings" : within 3 days AFTER earnings (IV crushed)
      - "dividend_window" : within 5 days of ex-div date
      - "normal" : nothing notable upcoming
    """

    ticker: str
    next_earnings_date: Optional[str] = None
    days_until_earnings: Optional[int] = None
    earnings_time: Optional[str] = None  # "bmo" | "amc" | None
    next_exdiv_date: Optional[str] = None
    days_until_exdiv: Optional[int] = None
    next_dividend_amount: Optional[float] = None
    iv_environment: str = "normal"


# Cache layout: {ticker.upper(): (CyclePosition, fetched_at_epoch)}
_cache: dict[str, tuple[CyclePosition, float]] = {}


def _api_key() -> Optional[str]:
    key = (get_settings().finnhub_api_key or "").strip()
    return key or None


async def _fetch_earnings(symbol: str) -> Optional[dict]:
    """Returns the NEXT earnings event for a symbol, or None."""
    key = _api_key()
    if not key:
        return None
    today = datetime.now(timezone.utc).date()
    end = today + timedelta(days=60)
    params = {
        "from": today.isoformat(),
        "to": end.isoformat(),
        "symbol": symbol.upper(),
        "token": key,
    }
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(f"{_BASE}/calendar/earnings", params=params)
        if r.status_code != 200:
            return None
        data = r.json()
    except Exception as e:  # noqa: BLE001
        log.warning("cycles.earnings.error", symbol=symbol, error=str(e))
        return None

    rows = data.get("earningsCalendar") or []
    if not rows:
        return None
    # Earliest by date
    rows.sort(key=lambda r: r.get("date") or "9999-12-31")
    return rows[0]


async def _fetch_dividend(symbol: str) -> Optional[dict]:
    """Returns the NEXT ex-dividend event for a symbol, or None."""
    key = _api_key()
    if not key:
        return None
    today = datetime.now(timezone.utc).date()
    end = today + timedelta(days=90)
    params = {
        "from": today.isoformat(),
        "to": end.isoformat(),
        "symbol": symbol.upper(),
        "token": key,
    }
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(f"{_BASE}/calendar/dividend", params=params)
        if r.status_code != 200:
            return None
        data = r.json()
    except Exception as e:  # noqa: BLE001
        log.warning("cycles.dividend.error", symbol=symbol, error=str(e))
        return None

    rows = data.get("dividendCalendar") or data.get("dividends") or []
    if not rows:
        return None
    rows.sort(key=lambda r: r.get("exDate") or r.get("date") or "9999-12-31")
    return rows[0]


def _days_between(iso_date: str) -> Optional[int]:
    try:
        d = datetime.fromisoformat(iso_date).date()
    except (TypeError, ValueError):
        return None
    today = datetime.now(timezone.utc).date()
    return (d - today).days


def _classify_iv_environment(
    days_to_earnings: Optional[int],
    days_to_exdiv: Optional[int],
) -> str:
    """The single-word read the bot uses to pick strategies. Earnings
    proximity dominates - IV crush is the bigger structural edge."""
    if days_to_earnings is not None:
        if 0 < days_to_earnings <= 7:
            return "high"  # pre-earnings IV ramp
        if 0 == days_to_earnings:
            return "earnings_day"  # IV peaks today
        if -3 <= days_to_earnings < 0:
            return "post_earnings"  # IV crushed
    if days_to_exdiv is not None and -2 <= days_to_exdiv <= 5:
        return "dividend_window"
    return "normal"


async def get_cycle_position(symbol: str) -> CyclePosition:
    """Cached cycle position for one ticker. Fetches both calendars in
    parallel; merges into a single CyclePosition."""
    sym = symbol.upper()
    now = time.time()
    hit = _cache.get(sym)
    if hit is not None and (now - hit[1]) < _CACHE_TTL:
        return hit[0]

    earn_task = asyncio.create_task(_fetch_earnings(sym))
    div_task = asyncio.create_task(_fetch_dividend(sym))
    earn_row, div_row = await asyncio.gather(earn_task, div_task)

    pos = CyclePosition(ticker=sym)

    if earn_row:
        date = str(earn_row.get("date") or "")
        if date:
            pos.next_earnings_date = date
            pos.days_until_earnings = _days_between(date)
        # Finnhub uses "hour" with values: "bmo" (before mkt open),
        # "amc" (after mkt close), or empty.
        hr = str(earn_row.get("hour") or "").strip().lower()
        if hr in ("bmo", "amc"):
            pos.earnings_time = hr

    if div_row:
        exdiv = str(div_row.get("exDate") or div_row.get("date") or "")
        if exdiv:
            pos.next_exdiv_date = exdiv
            pos.days_until_exdiv = _days_between(exdiv)
        amt = div_row.get("amount") or div_row.get("dividend")
        if amt is not None:
            try:
                pos.next_dividend_amount = float(amt)
            except (TypeError, ValueError):
                pass

    pos.iv_environment = _classify_iv_environment(
        pos.days_until_earnings, pos.days_until_exdiv,
    )

    _cache[sym] = (pos, now)
    return pos


async def get_cycle_positions(symbols: list[str]) -> dict[str, CyclePosition]:
    """Bulk fetch for a watchlist. Calls per-ticker but caches each so
    repeated calls inside the 24h TTL are free."""
    tasks = [get_cycle_position(s) for s in symbols if s]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    out: dict[str, CyclePosition] = {}
    for sym, res in zip(symbols, results):
        if isinstance(res, CyclePosition):
            out[sym.upper()] = res
    return out
