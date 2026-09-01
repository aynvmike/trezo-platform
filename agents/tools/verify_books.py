"""verify_books.py -- read-only proof that every book is its own book.

Written for the 2026-09-01 audit fixes. Run from anywhere:

    .\\.venv\\Scripts\\python.exe tools\\verify_books.py [--minutes 120]

It NEVER writes and NEVER places an order. For each configured book it
binds that book's own credentials (accounts.bind_for_user), reads that
book's own Alpaca account + positions, and compares the internal ledger
(paper_accounts.current_cash_usd) against that book's OWN broker cash.
Before the TE-16 fix all three ledgers read identical to the cent; after
it each book must track its own broker. It also counts, over the last
N minutes of agent_messages: R:R-floor rejections (RR-2), execution
kills vs fills per lane (NET2), handler_failed crashes, and
approval_starvation alerts -- the symptoms the fixes are meant to stop.

Secrets are never printed (account numbers are masked to their last 4).
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import os
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
AGENTS = os.path.dirname(HERE)
os.chdir(AGENTS)  # pydantic Settings loads agents/.env from the CWD
sys.path.insert(0, AGENTS)

from app.brokers import accounts as acc  # noqa: E402
from app.brokers import alpaca  # noqa: E402
from app.runtime.persistence import _client  # noqa: E402


def _mask(s: str) -> str:
    return ("..." + s[-4:]) if s else "?"


def _f(x, default=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


async def check_books() -> None:
    books = acc.load_accounts()
    sb = _client()
    rows = (
        sb.table("paper_accounts")
        .select("user_id,current_cash_usd,updated_at,week_start_equity_usd,day_start_equity_usd")
        .execute()
        .data
        or []
    )
    ledger = {r["user_id"]: r for r in rows}
    print(f"# Books: {len(books)} configured, {len(rows)} paper_accounts rows")
    if acc.validation_report():
        print("  ! account validation problems:", acc.validation_report())

    cash_seen: dict[float, list[str]] = defaultdict(list)
    wse_seen: dict[float, list[str]] = defaultdict(list)
    for a in books:
        led = ledger.get(a.user_id, {})
        with acc.bind_for_user(a.user_id) as bound:
            if bound is None:
                print(f"- {a.account_id:8} [{a.user_id[:8]}] UNRESOLVED -- skipped (correct behaviour)")
                continue
            acct = await alpaca.get_account()
            pos = await alpaca.get_positions_strict()
        if acct is None:
            print(f"- {a.account_id:8} [{a.user_id[:8]}] broker account read FAILED (None) -- no verdict, no action")
            continue
        led_cash = _f(led.get("current_cash_usd"))
        if led_cash is None:
            verdict = "no ledger row"
        elif abs(led_cash - acct.cash) < 1.0:
            verdict = "ledger MATCHES OWN broker"
        else:
            verdict = f"ledger DIFFERS from own broker by {led_cash - acct.cash:+,.2f}"
        if led_cash is not None:
            cash_seen[round(led_cash, 2)].append(a.account_id)
        wse = _f(led.get("week_start_equity_usd"))
        if wse is not None:
            wse_seen[round(wse, 0)].append(a.account_id)
        syms = None if pos is None else sorted({str(p.get("symbol")) for p in pos})
        print(
            f"- {a.account_id:8} [{a.user_id[:8]}] acct#{_mask(acct.account_number)} "
            f"broker cash={acct.cash:,.2f} equity={acct.equity:,.2f} | "
            f"ledger cash={led_cash} -> {verdict} | "
            f"broker positions={'READ FAILED' if syms is None else len(syms)} {syms or ''} | "
            f"week_start_equity={wse} | ledger updated={led.get('updated_at')}"
        )
    clones = {k: v for k, v in cash_seen.items() if len(v) > 1}
    print("CLONED CASH ACROSS BOOKS (TE-16 symptom): " + (str(clones) if clones else "none"))
    wclones = {k: v for k, v in wse_seen.items() if len(v) > 1}
    print("CLONED WEEK-START EQUITY (PH-7 symptom):   " + (str(wclones) if wclones else "none"))


def check_messages(minutes: int) -> None:
    sb = _client()
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=minutes)).isoformat()
    msgs = (
        sb.table("agent_messages")
        .select("agent_name,kind,payload,created_at,user_id")
        .gte("created_at", since)
        .order("created_at", desc=True)
        .limit(5000)
        .execute()
        .data
        or []
    )
    print(f"\n# agent_messages, last {minutes} min: {len(msgs)} rows")
    kinds = Counter(m.get("kind") for m in msgs)
    print("  kinds:", dict(kinds))

    rr = [m for m in msgs if m.get("kind") == "error" and "below your" in str((m.get("payload") or {}).get("error", ""))]
    by_book = Counter(str(m.get("user_id") or (m.get("payload") or {}).get("user_id") or "?")[:8] for m in rr)
    print(f"  R:R-floor rejections (RR-2 symptom): {len(rr)}  by book: {dict(by_book)}")

    lanes: dict[str, Counter] = defaultdict(Counter)
    for m in msgs:
        p = m.get("payload") or {}
        lane = p.get("lane") or p.get("asset_type") or "unknown"
        k = m.get("kind")
        if k in ("signal", "approve", "veto", "execute"):
            lanes[lane][k] += 1
        elif k == "error" and p.get("event") == "execute_error":
            lanes[lane]["execute_error"] += 1
        elif k == "error" and m.get("agent_name") == "trade_execution":
            lanes[lane]["te_error_untagged"] += 1
    for lane, c in sorted(lanes.items()):
        print(f"  lane {lane:8}: {dict(c)}")

    hf = [m for m in msgs if m.get("kind") == "error" and (m.get("payload") or {}).get("event") == "handler_failed"]
    print(f"  handler_failed (Net 1): {len(hf)}  " + (str(Counter((m.get('payload') or {}).get('agent') for m in hf)) if hf else ""))
    starve = [m for m in msgs if "approval_starvation" in str(m.get("payload"))]
    print(f"  approval_starvation alerts (Net 2): {len(starve)}")
    exec_by_book = Counter(str(m.get("user_id") or "?")[:8] for m in msgs if m.get("kind") == "execute")
    print(f"  executes by book: {dict(exec_by_book)}")


def check_option_ledgers() -> None:
    sb = _client()
    pp = (
        sb.table("paper_positions")
        .select("user_id,ticker,status")
        .eq("asset_type", "option")
        .eq("status", "open")
        .execute()
        .data
        or []
    )
    op = sb.table("options_positions").select("user_id,strategy,status,created_at").eq("status", "open").execute().data or []
    print("\n# Option ledgers (LT-05/LT-10)")
    print(f"  paper_positions open option rows: {len(pp)}  by book: {dict(Counter(str(r['user_id'])[:8] for r in pp))}")
    print(f"  options_positions open rows:      {len(op)}  by book: {dict(Counter(str(r['user_id'])[:8] for r in op))}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=int, default=120)
    args = ap.parse_args()
    asyncio.run(check_books())
    check_messages(args.minutes)
    check_option_ledgers()
    return 0


if __name__ == "__main__":
    sys.exit(main())
