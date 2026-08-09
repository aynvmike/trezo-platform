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

SOURCES, IN ORDER
1. Finnhub /stock/dividend -- generous call budget, but the endpoint is
   premium-gated on some plans and simply returns nothing when it is.
2. Alpha Vantage DIVIDENDS -- full history including PAST ex-dates and a
   numeric amount, which is exactly what is needed here, but the free
   tier allows only ~25 calls a day.

Hence the cache: one network call per symbol per day, at most. A handful
of income holdings therefore fits inside the smaller budget with room to
spare.

FAILURE POSTURE
Every path fails OPEN and returns None/[]. A missing calendar must never
stop a distribution from being modeled -- the manager falls back to the
holding's declared frequency, which is what it did before this module
existed. Nothing here raises.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from app.config import get_settings

FINNHUB_DIVIDEND_URL = "https://finnhub.io/api/v1/stock/dividend"
ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query"

# (symbol, iso-day) -> list[ExDividend]. Ex-dates do not change intraday.
_CACHE: dict = {}


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


async def ex_dividend_history(symbol: str) -> list:
    """Known ex-dates for a symbol, newest first. Cached one day."""
    sym = (symbol or "").upper().strip()
    if not sym:
        return []
    today = date.today().isoformat()
    hit = _CACHE.get((sym, today))
    if hit is not None:
        return hit

    s = get_settings()
    rows: list = []

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

    if not rows and getattr(s, "alpha_vantage_api_key", ""):
        data = await _get_json(ALPHA_VANTAGE_URL, {
            "function": "DIVIDENDS", "symbol": sym,
            "apikey": s.alpha_vantage_api_key,
        })
        rows = parse_alpha_vantage(sym, data)

    rows.sort(key=lambda e: e.ex_date, reverse=True)
    _CACHE[(sym, today)] = rows
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
