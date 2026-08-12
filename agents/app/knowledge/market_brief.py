"""Market brief -- the agents' own pre-market and pre-close read.

WHY ENGINE-SIDE (Mike, 2026-08-12): "do it the right way -- I want
everything to start being self reliant so we can avoid our
interference." The market reports used to be Nova scheduled tasks:
human-facing, PC-bound, and invisible to the agents. Same lesson as the
daily digest (2026-07-27) -- anything the agents should DEPEND on runs
in the engine, 24/7, with no Claude app in the loop.

TWO BRIEFS, WEEKDAYS (gated from ops_watchdog's tick):
  pre_market (~8:30-9:25 ET): per-book state, overnight crypto, market
    bias, today's most-traded names, earnings in the next 3 days for
    HELD symbols, ex-dividend dates in the next 7 for income holdings.
  pre_close (~15:25-16:00 ET): per-book day so far, open DAY orders
    that die at the close (the 2026-06-12 AAPL lesson: bracket legs
    with tif=day expire at 4 PM while the position lives on), and the
    crypto book that keeps trading overnight.

WHERE IT LANDS (all three, every run):
  1. TREZO_MARKET_BRIEF.md beside the daily digest -- Mike-readable.
  2. An activity-log line (event: market_brief) -- greppable history.
  3. A compact agent-memory note (mem0 digest buffer) -- recallable by
     every agent that consults memory before acting.
The DEEP material stays in the Quantconnect library by design: briefs
are operational awareness; the library is study.

Every section fails open: a missing feed shrinks the brief, never
blocks the tick. Nothing here places orders or changes settings.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Optional

BOOK_LABELS = {
    "cf1b0460-039d-40ac-adc8-7ca3ef17c5bb": "primary",
    "6ce61054-7ffd-41b5-80c3-1cd0220c79eb": "25k book",
    "49acafdd-1c86-4740-a1b1-f94aa7abce08": "75k book",
}


def _doc_path() -> Path:
    # Same root the daily digest writes to (repo root's parent = C:\Trezo).
    return (Path(__file__).resolve().parents[3] / "..").resolve() \
        / "TREZO_MARKET_BRIEF.md"


async def _books() -> list[dict]:
    """Per-book equity + day change + positions + open DAY orders."""
    out: list[dict] = []
    try:
        import json as _j
        import urllib.request as _u
        from app.brokers.accounts import load_accounts
        for a in load_accounts():
            try:
                req = _u.Request(a.base_url + "/v2/account",
                                 headers=a.headers())
                d = _j.load(_u.urlopen(req, timeout=15))
                eq = float(d.get("equity") or 0)
                last = float(d.get("last_equity") or eq) or eq
                req2 = _u.Request(
                    a.base_url + "/v2/orders?status=open&limit=50",
                    headers=a.headers())
                orders = _j.load(_u.urlopen(req2, timeout=15))
                day_orders = [o for o in orders
                              if str(o.get("time_in_force")) == "day"]
                req3 = _u.Request(a.base_url + "/v2/positions",
                                  headers=a.headers())
                pos = _j.load(_u.urlopen(req3, timeout=15))
                out.append({
                    "label": BOOK_LABELS.get(a.user_id, a.account_id),
                    "equity": eq,
                    "day_pct": (eq - last) / last * 100.0 if last else 0.0,
                    "positions": len(pos),
                    "open_orders": len(orders),
                    "day_orders": [f"{o.get('symbol')} {o.get('side')}"
                                   for o in day_orders][:6],
                })
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        pass
    return out


async def _crypto_overnight() -> list[str]:
    """12h move on the majors the books actually trade."""
    lines: list[str] = []
    try:
        from app.data.candles import fetch_candles_for
        for sym in ("BTC", "ETH", "SOL"):
            try:
                c = await fetch_candles_for(sym, "crypto")
                if not c or len(c) < 13:
                    continue
                now, then = float(c[-1].close), float(c[-13].close)
                if then > 0:
                    lines.append(f"{sym} {((now-then)/then*100.0):+.1f}%/12h")
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        pass
    return lines


async def _market_read() -> list[str]:
    lines: list[str] = []
    try:
        from app.strategies.market_filter import get_market_bias
        b = await get_market_bias()
        lines.append(f"bias: {getattr(b, 'bias', '?')} -- "
                     f"{str(getattr(b, 'note', '') or getattr(b, 'reason', ''))[:90]}")
    except Exception:  # noqa: BLE001
        pass
    try:
        from app.brokers.alpaca_data import get_most_actives
        act = await get_most_actives(top=10)
        if act:
            lines.append("most traded: " + ", ".join(act[:8]))
    except Exception:  # noqa: BLE001
        pass
    return lines


async def _held_symbols(client) -> list[str]:
    """Everything any book holds -- broker rows + income holdings."""
    syms: set[str] = set()
    try:
        import asyncio as _a
        def _q():
            return (client.table("paper_positions")
                    .select("ticker").eq("status", "open").execute())
        for r in ((await _a.to_thread(_q)).data or []):
            syms.add(str(r["ticker"]).upper())
        def _q2():
            return (client.table("user_positions")
                    .select("ticker, shares").gt("shares", 0).execute())
        for r in ((await _a.to_thread(_q2)).data or []):
            syms.add(str(r["ticker"]).upper())
    except Exception:  # noqa: BLE001
        pass
    return sorted(syms)[:30]


async def _earnings_watch(client) -> list[str]:
    """Earnings inside 3 days for names the books actually hold --
    binary-risk events the agents should not be surprised by."""
    try:
        held = await _held_symbols(client)
        if not held:
            return []
        from app.data.calendar_events import fetch_earnings_calendar
        evs = await fetch_earnings_calendar(held, days_ahead=3)
        return [f"{e.symbol} earnings {e.event_date} "
                f"({e.days_until}d)" for e in (evs or [])][:8]
    except Exception:  # noqa: BLE001
        return []


async def _ex_dividend_watch(client) -> list[str]:
    """Ex-dates inside 7 days for income holdings -- NAV drops by the
    distribution on these days; a naive read sees a loss."""
    out: list[str] = []
    try:
        import asyncio as _a
        from app.dividends.schedule import ex_dividend_history
        def _q():
            return (client.table("user_positions")
                    .select("ticker, shares").gt("shares", 0)
                    .gt("dist_yield_pct", 0).execute())
        rows = (await _a.to_thread(_q)).data or []
        today = _dt.date.today()
        for r in rows[:12]:
            try:
                hist = await ex_dividend_history(str(r["ticker"]))
                for e in hist[:3]:
                    d = _dt.date.fromisoformat(e.ex_date)
                    if 0 <= (d - today).days <= 7:
                        out.append(f"{r['ticker']} ex-div {e.ex_date}"
                                   + (f" (${e.amount}/sh)" if e.amount else ""))
                        break
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        pass
    return out[:8]


async def build_brief(client, kind: str) -> dict:
    """Assemble one brief. kind: 'pre_market' | 'pre_close'."""
    now = _dt.datetime.now(_dt.timezone.utc)
    books = await _books()
    crypto = await _crypto_overnight()
    market = await _market_read()
    sections: dict = {"kind": kind, "utc": now.isoformat()[:16],
                      "books": books, "crypto": crypto, "market": market}
    if kind == "pre_market" and client is not None:
        sections["earnings"] = await _earnings_watch(client)
        sections["ex_dividends"] = await _ex_dividend_watch(client)

    # ---- render ----
    title = ("PRE-MARKET BRIEF" if kind == "pre_market"
             else "PRE-CLOSE BRIEF")
    L: list[str] = [f"# {title} -- {now.strftime('%Y-%m-%d %H:%M')} UTC", ""]
    for b in books:
        L.append(f"- **{b['label']}**: ${b['equity']:,.0f} "
                 f"({b['day_pct']:+.2f}% today), {b['positions']} positions, "
                 f"{b['open_orders']} open orders")
        if kind == "pre_close" and b["day_orders"]:
            L.append(f"  - DAY orders that DIE at the close: "
                     + ", ".join(b["day_orders"]))
    if market:
        L.append("- market: " + " | ".join(market))
    if crypto:
        L.append("- crypto overnight: " + ", ".join(crypto))
    for key, label in (("earnings", "earnings watch (held names, 3d)"),
                       ("ex_dividends", "ex-dividend watch (7d)")):
        if sections.get(key):
            L.append(f"- {label}: " + "; ".join(sections[key]))
    if kind == "pre_close":
        L.append("- overnight: stocks close 16:00 ET; crypto lanes keep "
                 "trading -- position monitor stays on watch.")
    text = "\n".join(L)
    sections["text"] = text

    # ---- land it (all fail-open) ----
    try:  # 1. the file, newest brief on top
        p = _doc_path()
        old = p.read_text(encoding="utf-8") if p.exists() else ""
        p.write_text(text + "\n\n---\n\n" + old[:40000], encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    try:  # 2. activity log
        from app.agents.activity_log import record
        head = "; ".join(f"{b['label']} {b['day_pct']:+.1f}%" for b in books)
        record("market_brief", "MARKET",
               reason=f"[{kind}] {head} | " + " | ".join(market)[:150])
    except Exception:  # noqa: BLE001
        pass
    try:  # 3. agent memory (budget-friendly digest buffer)
        from app.memory.mem0_client import get_memory
        mc = get_memory()
        note = (f"{title}: "
                + "; ".join(f"{b['label']} {b['day_pct']:+.1f}%" for b in books)
                + ((" | " + ", ".join(crypto)) if crypto else "")
                + ((" | " + market[0]) if market else ""))
        mc.queue_note("market_brief", note[:400])
    except Exception:  # noqa: BLE001
        pass
    return sections
