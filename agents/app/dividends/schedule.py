"""Real ex-dividend schedules -- when a distribution actually lands.

WHY THIS EXISTS (2026-08-09)
The dividend manager used to pay every holding every 7 days on a modeled
yield. The annual dollars were about right; the TIMING was invented. That
made ex-date strategies -- laddering payouts so cash arrives when there
is something to buy, capture, staggering redeployment -- untestable,
because in the model every holding paid on the same clock.

This module supplies the missing fact: the dates a symbol actually went
ex-dividend, and for how much. With a real amount we stop estimating the
distribution from a yield entirely and use what the fund actually paid.

SOURCES, IN ORDER (AV-2/AV-3/AV-4, audit 2026-09-01)
1. Alpaca corporate actions (app/data/corporate_actions.py) -- the
   in-repo source the entry screen and the wheel universe already read:
   ex_date and rate back to 2016, ETFs included, on the broker key we
   already hold. This module was the last one still on the old chain.
2. Finnhub /stock/dividend -- kept as a cheap middle fallback only when a
   key is configured. The endpoint is NOT on this account's tier and
   returns nothing; it is not relied upon.
3. Alpha Vantage DIVIDENDS -- last resort. Full history and a numeric
   amount, but the free tier allows only ~25 calls a day, and a
   rate-limited response comes back HTTP 200 with a "Note"/"Information"
   body and no "data" -- which the old code parsed as "no dividends" and
   cached as the day's answer.

Hence the cache: one network call per symbol per day, at most -- but
only for a read that SUCCEEDED. A read that failed at every source is
retried after a short backoff instead of being remembered all day as
"this symbol pays nothing" (AV-4).

FAILURE POSTURE
Every path fails OPEN and returns None/[]. A missing calendar must never
stop a distribution from being modeled -- the manager falls back to the
holding's declared frequency, which is what it did before this module
existed. Nothing here raises. Failures are logged, not silent.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date
from typing import Optional

import structlog

from app.config import get_settings

log = structlog.get_logger("trezo.dividends.schedule")

FINNHUB_DIVIDEND_URL = "https://finnhub.io/api/v1/stock/dividend"
ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query"

# (symbol, iso-day) -> list[ExDividend]. Ex-dates do not change intraday.
# Populated ONLY by a successful read (AV-4).
_CACHE: dict = {}

# symbol -> unix time before which a failed read is not retried. Short on
# purpose: long enough not to hammer a 25-call/day budget with a key
# that is already rate-limited, short enough that the day's answer is
# not a failure frozen in place.
_FAIL_BACKOFF_SECONDS = 900
_FAILED_UNTIL: dict = {}


@dataclass(frozen=True)
class ExDividend:
    symbol: str
    ex_date: str      # ISO date
    amount: float     # per share, 0.0 when the source omitted it
    source: str

    def as_dict(self) -> dict:
        return {"symbol": self.symbol, "ex_date": self.ex_date,
                "amount": self.amount, "source": self.source}


def _parse_date(v) -> Optional[date]:
    try:
        return date.fromisoformat(str(v)[:10])
    except Exception:  # noqa: BLE001
        return None


def _to_float(v) -> float:
    try:
        f = float(v)
        return f if f == f and f not in (float("inf"), float("-inf")) else 0.0
    except Exception:  # noqa: BLE001
        return 0.0


async def _get_json(url: str, params: dict):
    """GET + parse JSON. Returns None on any failure -- never raises."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()
    except Exception:  # noqa: BLE001
        return None


def parse_finnhub(symbol: str, data) -> list:
    """Finnhub /stock/dividend -> [ExDividend]. Pure; unit-testable."""
    out: list = []
    if not isinstance(data, list):
        return out
    for r in data:
        if not isinstance(r, dict):
            continue
        ex = str(r.get("exDate") or r.get("date") or "")
        if not _parse_date(ex):
            continue
        out.append(ExDividend(symbol.upper(), ex[:10],
                              _to_float(r.get("amount")), "finnhub"))
    return out


def parse_alpha_vantage(symbol: str, data) -> list:
    """Alpha Vantage DIVIDENDS -> [ExDividend]. Pure; unit-testable."""
    out: list = []
    if not isinstance(data, dict):
        return out
    rows = data.get("data")
    if not isinstance(rows, list):
        return out
    for r in rows:
        if not isinstance(r, dict):
            continue
        ex = str(r.get("ex_dividend_date") or "")
        if not _parse_date(ex):
            continue
        out.append(ExDividend(symbol.upper(), ex[:10],
                              _to_float(r.get("amount")), "alpha_vantage"))
    return out


def parse_corporate_actions(symbol: str, rows) -> list:
    """Alpaca corporate-actions cash_dividend rows -> [ExDividend].

    Uses the DECLARED `rate`, not the split-adjusted `adj_rate`: this
    module answers "how much lands per share on that ex-date", which is
    the declared figure, the same thing Alpha Vantage's `amount` is.
    Pure; unit-testable.
    """
    out: list = []
    if not isinstance(rows, list):
        return out
    for r in rows:
        if not isinstance(r, dict):
            continue
        ex = str(r.get("ex_date") or "")
        if not _parse_date(ex):
            continue
        out.append(ExDividend(symbol.upper(), ex[:10],
                              _to_float(r.get("rate")),
                              "alpaca:corporate_actions"))
    return out


def _alpha_vantage_ok(data) -> bool:
    """Did Alpha Vantage actually ANSWER? A rate-limit or bad-key reply
    is HTTP 200 with a Note/Information/Error Message body and no
    "data" list -- that is a failed read, not an empty calendar."""
    return isinstance(data, dict) and isinstance(data.get("data"), list)


async def _alpaca_rows(sym: str) -> list:
    """Corporate-actions rows for `sym`, [] when unavailable. Module-level
    so a test can swap the source without planting anything in
    sys.modules. corporate_actions already caches a genuine empty
    calendar for a day and does NOT cache a failed fetch, so re-asking
    it is cheap in the one case and correct in the other."""
    try:
        from app.data.corporate_actions import dividend_history
        return await dividend_history(sym) or []
    except Exception as e:  # noqa: BLE001
        log.warning("dividend_schedule.corporate_actions_failed",
                    symbol=sym, error=str(e)[:160])
        return []


def _alpaca_answered(sym: str) -> bool:
    """Did Alpaca ANSWER for `sym` on this pass -- even with an empty
    calendar? dividend_history returns [] for "pays nothing" and for
    "call failed" alike, but corporate_actions caches ONLY successful
    reads, so a FRESH cache entry right after _alpaca_rows() is proof of
    an answer. Review 2026-09-01 (rv:data-lane, :191): without this a
    genuine non-payer was indistinguishable from an outage and, with no
    Alpha Vantage key (or its 25/day spent), warned 'unresolved' every
    15 minutes and was never cached for the day. Read-only peek; any
    surprise (module shape, missing cache) reads as "not answered", which
    is the old behaviour."""
    try:
        from app.data import corporate_actions as _ca
        hit = _ca._cache.get(sym)
        return bool(hit) and (time.time() - hit[1]) < _ca._CACHE_TTL
    except Exception:  # noqa: BLE001
        return False


async def _fetch_history(sym: str) -> tuple:
    """(rows, ok). `ok` is True only when SOME source answered; a chain
    that produced nothing but silence is a failed read (AV-4). An Alpaca
    answer of "no cash dividends" counts as an answer once the keyed
    fallbacks (Finnhub, Alpha Vantage) have also had their turn."""
    # 1. Alpaca corporate actions -- the in-repo source of record (AV-2).
    rows = parse_corporate_actions(sym, await _alpaca_rows(sym))
    if rows:
        return rows, True
    alpaca_answered = _alpaca_answered(sym)

    s = get_settings()

    # 2. Finnhub -- not on this tier; only tried when a key is present.
    if getattr(s, "finnhub_api_key", ""):
        # Finnhub needs an explicit window; ask for a wide one so past
        # ex-dates are included, which is what 'has it already gone ex'
        # requires and what the forward-only research fetcher omits.
        data = await _get_json(FINNHUB_DIVIDEND_URL, {
            "symbol": sym, "from": "2000-01-01",
            "to": date.today().replace(year=date.today().year + 1).isoformat(),
            "token": s.finnhub_api_key,
        })
        rows = parse_finnhub(sym, data)
        if rows:
            return rows, True

    # 3. Alpha Vantage -- last fallback, 25 calls/day (AV-3).
    if getattr(s, "alpha_vantage_api_key", ""):
        data = await _get_json(ALPHA_VANTAGE_URL, {
            "function": "DIVIDENDS", "symbol": sym,
            "apikey": s.alpha_vantage_api_key,
        })
        if _alpha_vantage_ok(data):
            return parse_alpha_vantage(sym, data), True
        reason = "no response"
        if isinstance(data, dict):
            reason = str(data.get("Note") or data.get("Information")
                         or data.get("Error Message") or "no data")[:120]
        log.warning("dividend_schedule.alpha_vantage_failed",
                    symbol=sym, reason=reason)

    # Nothing from any fallback. If Alpaca itself answered "no cash
    # dividends", that IS the day's answer (a confirmed non-payer), not a
    # failed read -- cache it and stop re-asking. Silence everywhere is
    # still a failed read.
    return [], alpaca_answered


async def ex_dividend_history(symbol: str) -> list:
    """Known ex-dates for a symbol, newest first. A successful read is
    cached for the day; a failed one is retried after a short backoff."""
    sym = (symbol or "").upper().strip()
    if not sym:
        return []
    today = date.today().isoformat()
    hit = _CACHE.get((sym, today))
    if hit is not None:
        return hit
    now = time.time()
    if now < _FAILED_UNTIL.get(sym, 0.0):
        return []                 # failed recently; fail open, do not re-spend

    rows, ok = await _fetch_history(sym)
    rows.sort(key=lambda e: e.ex_date, reverse=True)
    if ok:
        _CACHE[(sym, today)] = rows
        _FAILED_UNTIL.pop(sym, None)
    else:
        # AV-4: a read that failed is NOT the day's answer. Remember the
        # failure briefly so the next caller does not burn the budget
        # again, then try afresh.
        _FAILED_UNTIL[sym] = now + _FAIL_BACKOFF_SECONDS
        log.warning("dividend_schedule.unresolved", symbol=sym,
                    retry_in_s=_FAIL_BACKOFF_SECONDS)
    return rows


def select_unpaid(rows: list, last_paid: Optional[str],
                  today: Optional[date] = None):
    """The most recent ex-date that has arrived but not yet been paid.

    Pure so it can be tested without a network. Returns None when the
    holding is up to date -- which is the common case and must be cheap.
    """
    today = today or date.today()
    last_d = _parse_date(last_paid) if last_paid else None
    best = None
    for e in rows:
        ex = _parse_date(e.ex_date)
        if ex is None or ex > today:
            continue                      # not gone ex yet
        if last_d is not None and ex <= last_d:
            continue                      # already paid through this one
        if best is None or ex > _parse_date(best.ex_date):
            best = e
    return best


async def latest_unpaid_ex(symbol: str, last_paid: Optional[str],
                           today: Optional[date] = None):
    """Convenience: fetch history then pick the unpaid ex-date, or None."""
    try:
        rows = await ex_dividend_history(symbol)
    except Exception:  # noqa: BLE001
        return None
    return select_unpaid(rows, last_paid, today)


def clear_cache() -> None:
    _CACHE.clear()
    _FAILED_UNTIL.clear()
