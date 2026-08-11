"""Route guard -- the agents verify every order's route themselves.

WHY (2026-08-11)
Seven positions opened over 18 hours landed on the PRIMARY Alpaca account
while their ledger rows were tagged to the 25k and 75k books. Nothing
detected it; a human noticed empty order screens. The failure was silent
because binding an account and OWNING a book were checked nowhere at the
moment of action. This module is that check -- same philosophy as the
self-repair modules: the agents verify their own work, loudly, and refuse
rather than guess.

TWO LAYERS
1. check_route(user_id)  -- PRE-FLIGHT, called at the action points right
   after an account is bound. Compares the credentials about to be used
   against the account that owns the book. On mismatch the caller SKIPS:
   fail closed, never onto the primary.
2. audit_routes()        -- PERIODIC, called from ops_watchdog. For each
   book, compares broker-routed ledger rows against what that book's
   broker account actually holds. A row whose position is missing at its
   own broker but present at the primary is a MIS-ROUTED STRAY -- exactly
   today's pattern. Logged as route_orphan; auto-retag only when
   TREZO_ROUTE_AUTOREPAIR=true (default OFF -- detection is always on,
   repair is a decision).

SWITCHING THE DEFAULT BOOK (Mike's ask)
Which account is "the default" is now a SETTING, not a hardcode:
TREZO_DEFAULT_ACCOUNT (primary | acct2 | acct3). Fallbacks resolve to it,
so re-pointing the platform's default book is one env change -- no code.
"""

from __future__ import annotations

from typing import Optional, Tuple

from app.brokers.accounts import (
    account_for_user, current_account, multi_account_active, load_accounts,
)


def check_route(user_id: str) -> Tuple[bool, str]:
    """Is the currently BOUND account the one that owns this book?

    Single-account mode returns ok -- there is nothing to cross. Unknown
    books are refused outright: acting on a book we cannot resolve is how
    a stranger's order lands on the default account.
    """
    if not multi_account_active():
        return True, "single-account"
    uid = str(user_id or "")
    expected = account_for_user(uid)
    bound = current_account()
    if expected is None:
        return False, (f"unknown book {uid[:8]} -- refusing rather than "
                       f"falling back to "
                       f"{bound.account_id if bound else 'none'}")
    if bound is None or bound.key_id != expected.key_id:
        return False, (f"bound {bound.account_id if bound else 'NONE'} but "
                       f"book {uid[:8]} belongs to {expected.account_id}")
    return True, f"ok:{expected.account_id}"


def record_mismatch(ticker: str, user_id: str, note: str,
                    where: str) -> None:
    """One loud, greppable line per refusal. Never raises."""
    try:
        from app.agents.activity_log import record
        record("route_mismatch", str(ticker or "?"),
               reason=f"[{where}] {note}"[:290],
               extra={"user_id": str(user_id or "")})
    except Exception:  # noqa: BLE001
        pass


async def audit_routes() -> list[dict]:
    """Compare each book's broker-routed ledger rows against its broker.

    Returns findings; logs each as route_orphan. Fails open (returns [])
    on any data problem -- an audit must never take the platform down.
    """
    findings: list[dict] = []
    if not multi_account_active():
        return findings
    try:
        import json as _j
        import urllib.request as _u
        from app.brokers.accounts import primary_account
        from app.runtime.settings import _supabase  # same client the app uses
        client = _supabase()
        if client is None:
            return findings

        # What each broker account actually holds, by symbol.
        held: dict[str, set] = {}
        for acct in load_accounts():
            try:
                req = _u.Request(acct.base_url + "/v2/positions",
                                 headers=acct.headers())
                rows = _j.load(_u.urlopen(req, timeout=15))
                held[acct.account_id] = {
                    str(p.get("symbol", "")).upper().replace("/", "")
                    for p in rows}
            except Exception:  # noqa: BLE001
                held[acct.account_id] = None  # unreadable ≠ empty

        prim = primary_account()
        import asyncio as _a
        def _q():
            return (client.table("paper_positions")
                    .select("*")
                    .eq("status", "open").eq("broker", "alpaca").execute())
        ledger = (await _a.to_thread(_q)).data or []

        from datetime import datetime, timezone, timedelta
        _grace = datetime.now(timezone.utc) - timedelta(minutes=15)
        for r in ledger:
            # GRACE WINDOW: a just-submitted order is not a position yet
            # (/v2/positions shows fills only). Without this, every fresh
            # entry reads as an orphan for its first minutes -- the very
            # first live audit (8/11) flagged three SOXL rows that were
            # simply seconds old. Young rows get 15 minutes to fill.
            _op = str(r.get("opened_at") or r.get("created_at") or "")
            try:
                if _op and datetime.fromisoformat(
                        _op.replace("Z", "+00:00")) > _grace:
                    continue
            except Exception:  # noqa: BLE001
                pass
            uid = str(r.get("user_id") or "")
            acct = account_for_user(uid)
            if acct is None:
                continue
            mine = held.get(acct.account_id)
            if mine is None:
                continue  # couldn't read that broker; don't guess
            sym = str(r.get("ticker") or "").upper().replace("/", "")
            # Broker spells crypto as pairs: ledger ETH == broker ETHUSD.
            # Without this the first audit flagged three positions that
            # were routed perfectly (found live, 8/11).
            if sym in mine or f"{sym}USD" in mine:
                continue  # correctly routed
            at_primary = (prim is not None
                          and held.get(prim.account_id) is not None
                          and sym in held[prim.account_id])
            finding = {"ticker": sym, "book": acct.account_id,
                       "row_id": r.get("id"),
                       "present_at_primary": bool(at_primary)}
            findings.append(finding)
            try:
                from app.agents.activity_log import record
                record("route_orphan", sym,
                       reason=(f"ledger says {acct.account_id} but "
                               f"{acct.account_id}'s broker doesn't hold it"
                               + (" -- FOUND AT PRIMARY (mis-routed stray)"
                                  if at_primary else "")),
                       extra={"user_id": uid})
            except Exception:  # noqa: BLE001
                pass
            # Repair only the exact stray pattern, only when asked to.
            try:
                from app.config import get_settings
                if (at_primary and prim is not None
                        and getattr(get_settings(),
                                    "trezo_route_autorepair", False)):
                    def _fix(rid=r.get("id"), pu=prim.user_id):
                        return (client.table("paper_positions")
                                .update({"user_id": pu}).eq("id", rid)
                                .execute())
                    await _a.to_thread(_fix)
                    finding["repaired"] = True
            except Exception:  # noqa: BLE001
                pass
        return findings
    except Exception:  # noqa: BLE001
        return findings
