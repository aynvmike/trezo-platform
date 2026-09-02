"""Broker truth for OPTIONS — the ledger follows Alpaca, always.

WHY THIS EXISTS (2026-08-23)
Four short puts expiring 2026-08-21 sat 'open' in paper_positions all
weekend. They had expired worthless on Friday; Alpaca had already dropped
them. Nothing noticed. The engine logged `route_orphan` over and over --
"ledger says acct3 but acct3's broker doesn't hold it" -- which is the
engine correctly REFUSING to act on a position it cannot verify, but
refusing forever is not resolving.

Left alone this class of drift is quietly expensive: the new hard
collateral rule (spec §4 rule 5) reads open short puts as cash still
reserved, so four dead contracts would have withheld real buying power
from live trades on two books.

WHY THE EXISTING DETECTOR DIDN'T CATCH IT
`paper/stocks_reconcile.detect_option_drift_all_users` was written for
exactly this and had TWO defects: nothing ever called it (zero call
sites repo-wide), and it counted rows in `options_positions` -- a table
that holds ZERO open rows, because option positions actually live in
`paper_positions` with asset_type='option'. So even wired up it would
have compared the broker against an empty table and mis-flagged
everything as a phantom. A detector pointed at the wrong table is worse
than no detector: it reports confidently and wrongly. It was deleted on
2026-09-01 (audit, TE-17/LT-05); this module is the option-drift
detector.

BOOK-BOUND AND STRICT (OG-10, audit 2026-09-01). Each book's broker read
runs under bind_for_user(<that book>) with the route guard checked, and
it is the STRICT read: None means the read FAILED and the book is
skipped with a reason. A failed read that read as an empty broker would
alarm every live contract and close every expired one on the book.

WHAT THIS DOES
Per book, every pass:
  1. Ask Alpaca what option positions it actually holds (broker truth).
  2. Read the ledger's open option rows for that book.
  3. PHANTOM (ledger has it, broker doesn't):
       - past expiry + underlying settled OTM  -> close 'closed_expired',
         realized = premium kept (short) or premium lost (long)
       - past expiry + underlying settled ITM  -> flag 'closed_assigned'
         WITHOUT auto-closing: assignment moves shares and cash, and
         guessing that wrong is worse than a loud flag.
       - NOT past expiry                       -> flag only. A live
         contract missing from the broker is a routing incident, not
         housekeeping, and it must reach a human.
  4. ORPHAN (broker has it, ledger doesn't) -> flag. Adoption is the
     Options Scanner's job; this module never invents ledger rows.

The asymmetry is deliberate: it CLOSES only the unambiguous case (expired,
settled out of the money, nothing to move) and FLAGS everything else.
Reconcilers that guess produce phantom fixes, which are harder to find
than the drift they replaced.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import re
from typing import Any, Optional

import structlog

from app.config import get_settings

log = structlog.get_logger("trezo.broker_truth")

# OCC symbol: ROOT + YYMMDD + C/P + strike*1000 padded to 8
_OCC = re.compile(r"^(?P<root>[A-Z]+)(?P<y>\d{2})(?P<m>\d{2})(?P<d>\d{2})"
                  r"(?P<cp>[CP])(?P<strike>\d{8})$")


def parse_occ(symbol: str) -> Optional[dict]:
    """Break an OCC option symbol into its parts. None if it isn't one."""
    m = _OCC.match((symbol or "").upper().strip())
    if not m:
        return None
    try:
        return {
            "underlying": m.group("root"),
            "expiry": _dt.date(2000 + int(m.group("y")), int(m.group("m")),
                               int(m.group("d"))),
            "right": m.group("cp"),
            "strike": int(m.group("strike")) / 1000.0,
        }
    except ValueError:
        return None


def _supabase():
    s = get_settings()
    if not s.supabase_url or not s.supabase_service_role_key:
        return None
    try:
        from supabase import create_client
        return create_client(s.supabase_url, s.supabase_service_role_key)
    except Exception:  # noqa: BLE001
        return None


def settled_worthless(parsed: dict, underlying_price: float) -> Optional[bool]:
    """Did this contract expire out of the money?

    True  = expired worthless (safe to close at 0)
    False = expired in the money (assignment territory — do NOT auto-close)
    None  = cannot tell (no price) — treat as 'do not touch'
    """
    if underlying_price is None or underlying_price <= 0:
        return None
    if parsed["right"] == "P":
        return underlying_price > parsed["strike"]
    return underlying_price < parsed["strike"]


async def _underlying_price(symbol: str) -> Optional[float]:
    try:
        from app.data.candles import fetch_candles_for
        candles = await fetch_candles_for(symbol, "stock")
        return float(candles[-1].close) if candles else None
    except Exception:  # noqa: BLE001
        return None


async def _broker_option_symbols(user_id: str) -> tuple[Optional[set], Optional[str]]:
    """What Alpaca actually holds for THIS book.

    Returns (symbols, None) on a good read and (None, reason) when the
    book must be skipped. None must mean 'do nothing', never 'the broker
    holds nothing': a failed API call that read as an empty broker would
    close every expired option on the book and alarm every live one as a
    routing incident, every 15 minutes.

    OG-10 (rv:alpaca 1 / rv:bound-hunter 1, audit 2026-09-01):
      * The read is get_option_positions_strict. The display read
        get_option_positions() collapses a failed read into [], so the
        `rows is None` guard below was DEAD and a 429/timeout reconciled
        the book against an empty broker.
      * bind_for_user yields None for a book it cannot resolve. Reading
        on would compare that book against the PRIMARY's account and
        declare every row phantom; the book is skipped, with a reason.
      * The route is checked after binding, the same as Trade Execution
        and the other reconcilers: bind + check_route, then read.
    """
    try:
        from app.brokers.accounts import bind_for_user, should_skip_unresolved
        from app.brokers.route_guard import check_route, record_mismatch
        from app.brokers.alpaca import get_option_positions_strict
    except Exception as e:  # noqa: BLE001
        # No binder means no way to know WHICH account a read would hit.
        return None, f"broker binding unavailable: {str(e)[:80]}"
    try:
        with bind_for_user(user_id) as bound:
            if bound is None and should_skip_unresolved(user_id):
                log.warning("broker_truth.unresolved_book",
                            user_id=user_id[:8])
                return None, ("unresolved book — skipped, not defaulted "
                              "to the primary")
            ok, note = check_route(user_id)
            if not ok:
                log.warning("broker_truth.route_refused",
                            user_id=user_id[:8], note=note)
                record_mismatch("-", user_id, note, "broker_truth")
                return None, f"route refused: {note}"
            rows = await get_option_positions_strict()
    except Exception as e:  # noqa: BLE001
        log.warning("broker_truth.broker_read_failed",
                    user_id=user_id[:8], error=str(e)[:160])
        return None, "broker unreadable — took no action"
    if rows is None:
        log.warning("broker_truth.broker_read_failed",
                    user_id=user_id[:8], error="strict read returned None")
        return None, "broker unreadable — took no action"
    out = set()
    for r in rows:
        sym = (r.get("symbol") if isinstance(r, dict)
               else getattr(r, "symbol", None))
        if sym:
            out.add(str(sym).upper().strip())
    return out, None


async def reconcile_options_for_book(client, user_id: str,
                                     *, dry_run: bool = False) -> dict:
    """One book. Returns a report; closes only the unambiguous case."""
    report: dict[str, Any] = {
        "user_id": user_id, "closed": [], "flagged": [], "orphans": [],
        "checked": 0, "skipped_reason": None,
    }

    broker, why = await _broker_option_symbols(user_id)
    if broker is None:
        # OG-10: an unresolved book, a refused route or a failed read all
        # land here. Nothing is closed, nothing is flagged; the report
        # says why so a skipped book never looks like a clean one.
        report["skipped_reason"] = why or "broker unreadable — took no action"
        return report

    def _ledger():
        return (client.table("paper_positions")
                .select("id, ticker, side, quantity, entry_price, entry_at")
                .eq("user_id", user_id).eq("asset_type", "option")
                .eq("status", "open").execute())
    try:
        rows = (await asyncio.to_thread(_ledger)).data or []
    except Exception as e:  # noqa: BLE001
        report["skipped_reason"] = f"ledger unreadable: {str(e)[:120]}"
        return report

    report["checked"] = len(rows)
    today = _dt.datetime.now(_dt.timezone.utc).date()
    ledger_syms = set()

    for row in rows:
        sym = str(row.get("ticker") or "").upper().strip()
        ledger_syms.add(sym)
        if sym in broker:
            continue                      # tracked and held — correct

        parsed = parse_occ(sym)
        if parsed is None:
            report["flagged"].append(
                {"symbol": sym, "why": "not an OCC symbol — cannot judge"})
            continue

        if parsed["expiry"] >= today:
            # Live contract missing at the broker. This is a routing
            # incident: the order may have failed, or landed on another
            # account. Never silently closed.
            report["flagged"].append({
                "symbol": sym, "why": (
                    f"NOT expired (expires {parsed['expiry']}) but the "
                    f"broker does not hold it — routing incident, needs "
                    f"a human")})
            continue

        price = await _underlying_price(parsed["underlying"])
        worthless = settled_worthless(parsed, price)

        if worthless is None:
            report["flagged"].append({
                "symbol": sym, "why": (
                    f"expired {parsed['expiry']} but no price for "
                    f"{parsed['underlying']} — cannot tell worthless from "
                    f"assigned, left open")})
            continue

        if not worthless:
            report["flagged"].append({
                "symbol": sym, "why": (
                    f"expired {parsed['expiry']} IN the money "
                    f"({parsed['underlying']} {price:.2f} vs strike "
                    f"{parsed['strike']:.2f}) — likely ASSIGNED. Shares "
                    f"and cash move; not auto-closing")})
            continue

        qty = float(row.get("quantity") or 0)
        entry = float(row.get("entry_price") or 0)
        is_short = str(row.get("side") or "").lower() in ("short", "sell")
        # Short: premium collected is kept in full. Long: premium paid is
        # lost in full. Either way the contract settles at zero.
        pnl = round(entry * 100.0 * qty * (1.0 if is_short else -1.0), 2)

        if dry_run:
            report["closed"].append(
                {"symbol": sym, "realized": pnl, "dry_run": True})
            continue

        def _close(rid=row["id"], p=pnl, exp=parsed["expiry"]):
            return (client.table("paper_positions").update({
                "status": "closed_expired",
                "exit_price": 0,
                "exit_at": _dt.datetime(exp.year, exp.month, exp.day, 20, 0,
                                        tzinfo=_dt.timezone.utc).isoformat(),
                "realized_pnl_usd": p,
                "close_requested": False,
            }).eq("id", rid).execute())
        try:
            await asyncio.to_thread(_close)
            report["closed"].append({"symbol": sym, "realized": pnl})
            log.info("broker_truth.expired_closed", user_id=user_id[:8],
                     symbol=sym, realized=pnl)
        except Exception as e:  # noqa: BLE001
            report["flagged"].append(
                {"symbol": sym, "why": f"close failed: {str(e)[:120]}"})

    for sym in sorted(broker - ledger_syms):
        report["orphans"].append({
            "symbol": sym,
            "why": "held at the broker with no ledger row — needs adoption"})

    return report


async def reconcile_options_all_books(*, dry_run: bool = False) -> dict:
    client = _supabase()
    if client is None:
        return {"ok": False, "error": "Supabase not configured"}

    def _users():
        return client.table("paper_accounts").select("user_id").execute()
    try:
        users = (await asyncio.to_thread(_users)).data or []
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:200]}

    reports = []
    for u in users:
        uid = str(u.get("user_id") or "")
        if not uid:
            continue
        reports.append(await reconcile_options_for_book(
            client, uid, dry_run=dry_run))
    return {
        "ok": True,
        "books": len(reports),
        # OG-10: books that took no action (unresolved, route refused,
        # broker unreadable). Additive; the agent's summary is unchanged.
        "skipped": sum(1 for r in reports if r.get("skipped_reason")),
        "closed": sum(len(r["closed"]) for r in reports),
        "flagged": sum(len(r["flagged"]) for r in reports),
        "orphans": sum(len(r["orphans"]) for r in reports),
        "reports": reports,
    }
