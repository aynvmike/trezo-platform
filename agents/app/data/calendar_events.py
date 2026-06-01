"""Earnings and ex-dividend calendar — upcoming corporate events.

Phase 7.5. The Research agent uses this to warn ahead of events that
should change how strategies behave: an earnings report adds binary
risk; an ex-dividend date matters to the income strategies.

Both fetchers are best-effort. Finnhub's earnings calendar is on the
free tier; the dividend endpoint may be premium-gated. Either one
returning [] is fine — the Research agent just reports what it can see.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date, timedelta

from app.config import get_settings


FINNHUB_EARNINGS_URL = "https://finnhub.io/api/v1/calendar/earnings"
FINNHUB_DIVIDEND_URL = "https://finnhub.io/api/v1/stock/dividend"


@dataclass
class CalendarEvent:
    symbol: str
    event_type: str    # 'earnings' | 'ex_dividend'
    event_date: str    # ISO date
    days_until: int
    detail: str

    def to_dict(self) -> dict:
        return asdict(self)


def _days_until(iso_date: str) -> int:
    try:
        d = date.fromisoformat(iso_date[:10])
        return (d - date.today()).days
    except Exception:  # noqa: BLE001
        return -1


async def _get_json(url: str, params: dict):
    """GET + parse JSON. Returns None on any failure — never raises."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()
    except Exception:  # noqa: BLE001
        return None


async def fetch_earnings_calendar(
    symbols: list[str], days_ahead: int = 10
) -> list[CalendarEvent]:
    """Upcoming earnings reports for the given symbols (Finnhub free tier)."""
    key = get_settings().finnhub_api_key
    if not key or not symbols:
        return []
    today = date.today()
    data = await _get_json(FINNHUB_EARNINGS_URL, {
        "from": today.isoformat(),
        "to": (today + timedelta(days=days_ahead)).isoformat(),
        "token": key,
    })
    if not isinstance(data, dict):
        return []
    rows = data.get("earningsCalendar") or []
    wanted = {s.upper() for s in symbols}
    out: list[CalendarEvent] = []
    for r in rows:
        sym = str(r.get("symbol") or "").upper()
        if sym not in wanted:
            continue
        ev_date = str(r.get("date") or "")
        if not ev_date:
            continue
        du = _days_until(ev_date)
        if du < 0:
            continue
        hour = str(r.get("hour") or "").lower()
        when = {"bmo": "before the open", "amc": "after the close"}.get(hour, "")
        est = r.get("epsEstimate")
        detail = f"Earnings {ev_date}"
        if when:
            detail += f" ({when})"
        if est is not None:
            detail += f", EPS est {est}"
        out.append(CalendarEvent(sym, "earnings", ev_date, du, detail))
    return out


async def fetch_ex_dividends(
    symbols: list[str], days_ahead: int = 14
) -> list[CalendarEvent]:
    """Upcoming ex-dividend dates. Best-effort — Finnhub's dividend
    endpoint may be premium-gated, in which case this returns []."""
    key = get_settings().finnhub_api_key
    if not key or not symbols:
        return []
    today = date.today()
    out: list[CalendarEvent] = []
    for sym in symbols:
        data = await _get_json(FINNHUB_DIVIDEND_URL, {
            "symbol": sym.upper(),
            "from": today.isoformat(),
            "to": (today + timedelta(days=days_ahead)).isoformat(),
            "token": key,
        })
        if not isinstance(data, list):
            continue
        for r in data:
            ex = str(r.get("exDate") or r.get("date") or "")
            if not ex:
                continue
            du = _days_until(ex)
            if du < 0 or du > days_ahead:
                continue
            amt = r.get("amount")
            detail = f"Ex-dividend {ex}"
            if amt is not None:
                detail += f", ${amt} per share"
            out.append(CalendarEvent(sym.upper(), "ex_dividend", ex, du, detail))
    return out
