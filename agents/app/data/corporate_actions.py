"""Dividend truth from Alpaca corporate actions — one source, real dates.

WHY THIS EXISTS (2026-08-23)
The §4 entry screen needs a dividend raise streak, a cut history, and an
ex-date. The first build asked Finnhub for the payment series and got
"you don't have access to this resource", so the screen admitted nothing.
The second build substituted `dividendGrowthRate5Y`, which INVERTS the
rule it proxies: a company that cut to zero and restarted shows a huge
5Y CAGR off a near-zero base, so TMUS (+124%) and Ford (+38%) ranked at
the TOP of a ladder whose screen exists to exclude exactly them.

Then the obvious question got asked -- can one source answer all of it --
and the answer was sitting in the broker we already pay attention to.
Alpaca's /v1/corporate-actions returns, free:

    ex_date, record_date, payable_date, rate, special, symbol

...back to at least 2016 (a full 10-year window for the streak and cut
rules), AND it covers ETFs, which Finnhub's fundamentals do not. SCHD,
VYM and JEPI all return distributions here while Finnhub's profile2
returns an empty object for them.

So this module replaces BOTH earlier approaches with the real series:
  - raise streak and cut history from actual payments, not a CAGR
  - trailing yield computed from actual distributions / price, which is
    the only way ETFs get a yield at all
  - the NEXT ex-date, which the wheel advisor's ex-date guard needs and
    was silently receiving as None

`special: true` payments are excluded from streak and trend maths on
purpose -- a one-off special dividend is not a raise, and counting it as
one would manufacture a streak that breaks the following year.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import time
from collections import defaultdict
from typing import Optional

import structlog

from app.config import get_settings

log = structlog.get_logger("trezo.corporate_actions")

CA_URL = "https://data.alpaca.markets/v1/corporate-actions"

# Payments barely change; a day of cache is generous and keeps the
# screen's per-build cost near zero.
_CACHE_TTL = 24 * 3600
_cache: dict[str, tuple[list, float]] = {}


def _auth() -> Optional[dict]:
    s = get_settings()
    key = getattr(s, "alpaca_api_key", "") or ""
    sec = getattr(s, "alpaca_secret_key", "") or ""
    if not key or not sec:
        return None
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": sec}


async def dividend_history(symbol: str, years: int = 11) -> list:
    """Every cash dividend for `symbol` over the window, oldest first.

    Returns [] when the symbol genuinely pays nothing, and [] on failure
    too — callers must treat an empty list as "no evidence", never as
    "confirmed non-payer". The screen's UNVERIFIED path is what keeps
    that distinction honest.
    """
    sym = (symbol or "").upper().strip()
    if not sym:
        return []
    now = time.time()
    hit = _cache.get(sym)
    if hit and (now - hit[1]) < _CACHE_TTL:
        return hit[0]

    headers = _auth()
    if headers is None:
        return []

    today = _dt.datetime.now(_dt.timezone.utc).date()
    start = today.replace(year=today.year - years)
    # Look FORWARD as well. Announced-but-not-yet-reached ex-dates are
    # the entire point of the ex-date guard, and querying end=today
    # returned none of them -- which is why lane rule 3 was being handed
    # None on every call and could never fire.
    horizon = today + _dt.timedelta(days=150)
    rows: list = []
    page: Optional[str] = None
    try:
        import httpx
        async with httpx.AsyncClient(timeout=20.0) as client:
            while True:
                params = {
                    "symbols": sym, "types": "cash_dividend",
                    "start": start.isoformat(), "end": horizon.isoformat(),
                    "limit": 1000,
                }
                if page:
                    params["page_token"] = page
                r = await client.get(CA_URL, params=params, headers=headers)
                if r.status_code != 200:
                    log.warning("corporate_actions.http",
                                symbol=sym, status=r.status_code)
                    return []
                data = r.json() or {}
                block = (data.get("corporate_actions") or {})
                rows.extend(block.get("cash_dividends") or [])
                page = data.get("next_page_token")
                if not page:
                    break
    except Exception as e:  # noqa: BLE001
        log.warning("corporate_actions.failed", symbol=sym, error=str(e)[:160])
        return []

    rows.sort(key=lambda r: str(r.get("ex_date") or ""))
    _cache[sym] = (rows, now)
    return rows


def _by_year(rows: list, *, include_special: bool = False) -> dict:
    """Total ordinary dividends per calendar year, keyed by ex-date year.

    Special dividends are excluded by default: a one-off is not a raise,
    and folding it in would invent a streak that breaks next year.
    """
    out: dict = defaultdict(float)
    for r in rows:
        if not include_special and bool(r.get("special")):
            continue
        ex = str(r.get("ex_date") or "")
        try:
            year = int(ex[:4])
            rate = float(r.get("rate") or 0)
        except (TypeError, ValueError):
            continue
        if rate > 0:
            out[year] += rate
    return dict(out)


def _complete_years(rows: list) -> dict:
    """Yearly totals, corrected for payment-TIMING artifacts.

    THE PROBLEM, found on Realty Income (O). It raised its monthly
    dividend every single year 2016->2023, yet the screen scored its
    streak at ZERO. Cause: 2024 recorded 11 payments (total understated
    at 2.869) and 2025 recorded 13 (overstated at 3.487) because one
    monthly payment slipped across a year boundary. Nothing about the
    dividend changed; the calendar moved.

    Dropping short years does not fix it either — that leaves a GAP in
    the year sequence, and a streak that requires consecutive years then
    breaks anyway. That is precisely how a 25-year Dividend Aristocrat
    came back as "raise streak 0y".

    So a year whose payment count is CLOSE to the norm is normalised to
    the modal count (total * modal / actual) rather than discarded: a
    timing shift is corrected, not treated as a dividend change. A year
    that is far off the norm — a genuinely suspended or skipped payout —
    is left RAW, because that is a real reduction and the cut rule
    should see it.

    The current (in-progress) year is always dropped; it is incomplete
    by definition, not by artifact.
    """
    counts: dict = defaultdict(int)
    totals = _by_year(rows)
    for r in rows:
        if bool(r.get("special")):
            continue
        try:
            counts[int(str(r.get("ex_date"))[:4])] += 1
        except (TypeError, ValueError):
            continue
    if not counts:
        return {}
    current = _dt.datetime.now(_dt.timezone.utc).year
    freq: dict = defaultdict(int)
    for y, n in counts.items():
        if y != current:
            freq[n] += 1
    if not freq:
        return {}
    modal = max(freq.items(), key=lambda kv: (kv[1], kv[0]))[0]

    # Within this many payments of the norm = a timing shift, normalise.
    # Beyond it = a real change in payout behaviour, leave it alone.
    TIMING_TOLERANCE = 2

    out: dict = {}
    for y, total in totals.items():
        if y == current:
            continue                       # always incomplete
        n = counts.get(y, 0)
        if n <= 0:
            continue
        if n == modal:
            out[y] = total
        elif abs(n - modal) <= TIMING_TOLERANCE:
            out[y] = total * (modal / float(n))
        else:
            out[y] = total                 # genuinely irregular — raw
    return out


def window_years(rows: list) -> int:
    """How many COMPLETE years of history we actually have."""
    return len(_complete_years(rows))


def raise_streak_years(rows: list) -> Optional[int]:
    """Consecutive COMPLETE years of a higher total dividend, newest
    first. None when there is not enough history to say.

    The current (partial) year is skipped — a year still in progress has
    not failed to raise yet, and counting it would reset every streak in
    January.
    """
    by_year = _complete_years(rows)
    if len(by_year) < 2:
        return None
    current = _dt.datetime.now(_dt.timezone.utc).year
    years = sorted((y for y in by_year if y < current), reverse=True)
    if len(years) < 2:
        return None
    streak = 0
    for a, b in zip(years, years[1:]):
        if a - b != 1:
            break            # a gap in payments ends the streak
        if by_year[a] > by_year[b]:
            streak += 1
        else:
            break
    return streak


def had_cut(rows: list, lookback_years: int = 10) -> Optional[bool]:
    """Did the annual dividend ever FALL year-over-year in the window?

    A >5% drop counts; smaller wobbles are timing noise (a payment that
    lands either side of a year boundary shifts an annual total without
    the dividend having changed).
    """
    by_year = _complete_years(rows)
    if len(by_year) < 2:
        return None
    current = _dt.datetime.now(_dt.timezone.utc).year
    years = sorted((y for y in by_year
                    if y < current and y >= current - lookback_years),
                   reverse=True)
    if len(years) < 2:
        return None
    for a, b in zip(years, years[1:]):
        if a - b != 1:
            continue
        if by_year[a] < by_year[b] * 0.95:
            return True
    return False


def trailing_12mo_dividends(rows: list) -> Optional[float]:
    """Sum of the last 12 months of dividends, specials INCLUDED.

    Specials count here on purpose: this measures cash actually received,
    which is the right basis for a yield even though it is the wrong
    basis for a streak.
    """
    if not rows:
        return None
    today = _dt.datetime.now(_dt.timezone.utc).date()
    cutoff = today - _dt.timedelta(days=365)
    total = 0.0
    seen = False
    for r in rows:
        try:
            ex = _dt.date.fromisoformat(str(r.get("ex_date"))[:10])
            rate = float(r.get("rate") or 0)
        except (TypeError, ValueError):
            continue
        if ex >= cutoff and rate > 0:
            total += rate
            seen = True
    return total if seen else None


def trailing_yield(rows: list, price: float) -> Optional[float]:
    """Trailing-12-month yield from ACTUAL distributions.

    This is what gives ETFs a yield at all — Finnhub's fundamentals do
    not cover funds, so SCHD/VYM/JEPI were permanently UNVERIFIED and
    excluded from the ladder. They are the natural core of a ladder at
    small capital, so that hole mattered.
    """
    ttm = trailing_12mo_dividends(rows)
    if ttm is None or not price or price <= 0:
        return None
    return ttm / float(price)


def next_ex_date(rows: list) -> Optional[str]:
    """The next KNOWN ex-date, or None.

    Feeds the wheel advisor's ex-date guard (lane rule 3), which until
    now was being handed None on every call — so the rule that stops a
    covered call losing its dividend to early exercise could never
    actually fire.
    """
    today = _dt.datetime.now(_dt.timezone.utc).date()
    upcoming = []
    for r in rows:
        try:
            ex = _dt.date.fromisoformat(str(r.get("ex_date"))[:10])
        except (TypeError, ValueError):
            continue
        if ex >= today:
            upcoming.append(ex)
    return min(upcoming).isoformat() if upcoming else None


def last_dividend_rate(rows: list) -> Optional[float]:
    """Most recent per-share payment — the amount an early exercise would
    take, which is what the ex-date guard weighs against time value."""
    for r in reversed(rows):
        try:
            rate = float(r.get("rate") or 0)
        except (TypeError, ValueError):
            continue
        if rate > 0:
            return rate
    return None


async def dividend_profile(symbol: str, price: Optional[float] = None) -> dict:
    """Everything the screen needs about one name's dividend, in one call.

    `verified` says whether the payment series was actually retrieved —
    the screen must not treat a failed fetch as a confirmed non-payer.
    """
    rows = await dividend_history(symbol)
    return {
        "symbol": (symbol or "").upper().strip(),
        "verified": bool(rows),
        "payments": len(rows),
        "raise_streak_years": raise_streak_years(rows),
        "had_cut": had_cut(rows),
        "ttm_dividends": trailing_12mo_dividends(rows),
        "trailing_yield": (trailing_yield(rows, price)
                           if price is not None else None),
        "next_ex_date": next_ex_date(rows),
        "last_rate": last_dividend_rate(rows),
        "years_covered": sorted(_complete_years(rows).keys()),
        # How deep the evidence goes. Alpaca's corporate actions begin in
        # 2016, so a 10-year streak is not yet EXPRESSIBLE -- ten complete
        # years yield at most nine year-over-year comparisons. The screen
        # asks for an unbroken record across everything visible rather
        # than a fixed number, which is honest today and tightens on its
        # own as the history deepens.
        "window_years": window_years(rows),
    }
