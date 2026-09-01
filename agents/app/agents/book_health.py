"""Book health -- does each book still add up?

WHY (2026-08-18)
Every existing check asks whether a COMPONENT is working: is the agent
ticking, did the order fill, is the API reachable. All of those were
green on 8/17 while the 25k and 75k books held seventeen positions
Trezo had no record of -- no stop, no target, no ladder, and on crypto
no broker bracket either. Every part was working. The whole did not add
up, and nothing was asking that question.

So this agent checks INVARIANTS, per book, and it is deliberately blunt
about the one that matters:

    UNMANAGED NOTIONAL -- the dollar value of positions the broker holds
    that our ledger has no open row for.

That number should be zero. On 8/17 it was most of two books. It was
computable all along from data we already had; nobody had written the
subtraction down.

The other checks follow the same shape -- a fact that should be true,
stated plainly, alarmed when it stops being true:

  * a position sitting PAST its own stop while still open (the exit did
    not fire -- the stop exists and did nothing)
  * a book halted while its own counters say the condition has cleared
    (the latched kill-switch, 8/17)

Those three are what this agent implements (G6: the header used to
promise two more -- "zero approvals across a market-hours window" and
"ledger vs broker position COUNT" -- that were never written). The
starvation question lives in ops_watchdog._check_flow(), per lane; the
count question is answered by invariant 1, which lists the rows
themselves rather than comparing two totals.

Dust (DU-01): a broker row worth less than DUST_MIN_USD is NOT an
unmanaged position -- it is the crumb a fractional close leaves behind
-- and is skipped. A row whose market_value is MISSING or unparseable
still flags: a failed read must never read as "nothing there".

Findings go out through app.runtime.alerts, which is the channel this
platform did not have. Detection was never the problem.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from app.runtime import book_scope
from app.runtime.alerts import notify
from app.runtime.asset_policy import policy_for

from .base import Agent, AgentMessage


def _f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


# A book with ANY unmanaged position is broken; above this it is urgent.
URGENT_UNMANAGED_USD = _f("TREZO_HEALTH_URGENT_USD", 1000.0)
# DU-01: below this a broker row is dust (fractional-close residue),
# not an unmanaged position. Only a PRESENT, PARSEABLE market_value can
# qualify as dust; a missing one is never assumed small.
DUST_MIN_USD = _f("TREZO_HEALTH_DUST_USD", 1.00)


def _supabase():
    from app.config import get_settings
    s = get_settings()
    if not (s.supabase_url and s.supabase_service_role_key):
        return None
    try:
        from supabase import create_client
        return create_client(s.supabase_url, s.supabase_service_role_key)
    except Exception:  # noqa: BLE001
        return None


def _ledger_key(broker_row: dict) -> tuple[str, str]:
    """(ticker, side) as the ledger would store it."""
    sym = str(broker_row.get("symbol") or "").upper().strip()
    ac = str(broker_row.get("asset_class") or "").lower()
    if ac == "crypto" or "/" in sym:
        if "/" in sym:
            sym = sym.split("/", 1)[0]
        elif sym.endswith("USD") and len(sym) > 4:
            sym = sym[:-3]
    try:
        qty = float(broker_row.get("qty") or 0)
    except (TypeError, ValueError):
        qty = 0.0
    return (sym, "long" if qty >= 0 else "short")


class BookHealthAgent(Agent):
    """One question per book: does it add up? Then say so, out loud."""

    name = "book_health"
    tick_interval_seconds = 300      # every 5 min; the checks are cheap

    # Remembered so we can announce RECOVERY too. A channel that only
    # ever reports bad news gets muted; one that closes its own loops
    # stays trusted.
    _open_findings: dict[str, str] = {}

    _announced: bool = False

    async def tick(self) -> list[AgentMessage]:
        out: list[AgentMessage] = []
        # Prove the channel on the first tick after every restart. If the
        # engine comes back and this does NOT arrive, the channel is
        # broken -- which is exactly the thing you cannot afford to
        # discover later, during the incident it was meant to report.
        if not type(self)._announced:
            type(self)._announced = True
            try:
                from app.runtime.alerts import configured, notify
                if configured():
                    await notify(
                        "Engine started",
                        "Book health monitor is live. You will hear from "
                        "this channel when a book stops adding up, when a "
                        "position sits past its own stop, or when a halt "
                        "outlives its cause.",
                        severity="good", key="")
            except Exception:  # noqa: BLE001
                pass
        client = _supabase()
        if client is None:
            return out
        try:
            from app.brokers.accounts import load_accounts
            books = load_accounts()
        except Exception:  # noqa: BLE001
            return out

        for acct in books:
            uid = acct.account_key
            label = acct.label or acct.account_id
            try:
                findings = await self._check_book(client, uid, label)
            except Exception as e:  # noqa: BLE001
                out.append(AgentMessage(
                    agent=self.name, kind="error",
                    payload={"user_id": uid,
                             "error": f"book health check failed: {str(e)[:160]}"}))
                continue
            for f in findings:
                out.append(AgentMessage(agent=self.name, kind="alert",
                                        payload={**f, "user_id": uid}))
        return out

    # -----------------------------------------------------------------

    async def _check_book(self, client, uid: str, label: str) -> list[dict]:
        findings: list[dict] = []

        broker = await book_scope.positions(uid, where="book_health")
        if broker is None:
            # Could not check. Say nothing -- a broker blip is not a
            # book problem, and crying wolf is how a channel dies.
            return findings

        def _open():
            return (client.table("paper_positions")
                    .select("id, ticker, side, quantity, entry_price, "
                            "stop_price, asset_type")
                    .eq("user_id", uid).eq("status", "open").execute())
        rows = (await self._thread(_open)).data or []
        have = {(str(r.get("ticker") or "").upper(),
                 str(r.get("side") or "long")) for r in rows}

        # ---- INVARIANT 1: unmanaged notional should be zero ----------
        unmanaged, unmanaged_usd = [], 0.0
        for bp in broker:
            key = _ledger_key(bp)
            if key in have:
                continue
            # DU-01: skip a row ONLY when market_value is present, parses
            # and sits below the dust floor. Missing or unparseable is
            # not "small" -- it is unknown, and unknown still flags.
            mv_raw = bp.get("market_value")
            mv = None
            if mv_raw is not None and str(mv_raw).strip() != "":
                try:
                    mv = abs(float(mv_raw))
                except (TypeError, ValueError):
                    mv = None
            if mv is not None and mv < DUST_MIN_USD:
                continue
            unmanaged.append(f"{key[0]} (${mv:,.0f})" if mv is not None
                             else f"{key[0]} ($? -- no market value)")
            unmanaged_usd += mv or 0.0

        fkey = f"unmanaged:{uid}"
        if unmanaged:
            sev = "urgent" if unmanaged_usd >= URGENT_UNMANAGED_USD else "warn"
            body = (
                f"The broker holds **{len(unmanaged)}** position(s) worth "
                f"**${unmanaged_usd:,.0f}** that this book has no open row "
                f"for. Nothing is managing them: no stop, no target, no "
                f"profit ladder. Crypto has no broker bracket either, so "
                f"those are unprotected outright.\n\n"
                + ", ".join(unmanaged[:12]))
            await notify(f"{label}: ${unmanaged_usd:,.0f} unmanaged",
                         body, severity=sev, key=fkey,
                         fields={"book": label,
                                 "broker positions": len(broker),
                                 "open ledger rows": len(rows)})
            self._open_findings[fkey] = "unmanaged"
            findings.append({"finding": "unmanaged_positions",
                             "count": len(unmanaged),
                             "notional_usd": round(unmanaged_usd, 2)})
        elif self._open_findings.pop(fkey, None):
            await notify(f"{label}: every position is managed again",
                         f"All {len(broker)} broker position(s) now have a "
                         f"matching open row.", severity="good", key="")

        # ---- INVARIANT 2: an open position past its own stop ---------
        past: list[str] = []
        for r in rows:
            try:
                stop = float(r.get("stop_price") or 0)
            except (TypeError, ValueError):
                continue
            if stop <= 0:
                continue
            price = await self._price(str(r.get("ticker")),
                                      str(r.get("asset_type") or "stock"))
            if price is None:
                continue
            side = str(r.get("side") or "long")
            if (side == "long" and price <= stop) or (
                    side != "long" and price >= stop):
                past.append(f"{r.get('ticker')} @ {price:g} vs stop {stop:g}")

        fkey2 = f"paststop:{uid}"
        if past:
            await notify(
                f"{label}: {len(past)} position(s) past their stop and still open",
                "The stop exists and did not fire. Either the exit path is "
                "failing or the monitor is not reaching these rows.\n\n"
                + "\n".join(past[:10]),
                severity="urgent", key=fkey2, fields={"book": label})
            self._open_findings[fkey2] = "past_stop"
            findings.append({"finding": "past_stop", "count": len(past)})
        elif self._open_findings.pop(fkey2, None):
            await notify(f"{label}: no positions past their stop",
                         "Cleared.", severity="good", key="")

        # ---- INVARIANT 3: a halt that its own counters do not support -
        def _acct():
            return (client.table("paper_accounts")
                    .select("trading_halted, halt_reason, halt_scope, "
                            "consecutive_losses, today_realized_pnl_usd, halted_at")
                    .eq("user_id", uid).limit(1).execute())
        arows = (await self._thread(_acct)).data or []
        if arows:
            a = arows[0]
            fkey3 = f"stalehalt:{uid}"
            stale = (a.get("trading_halted")
                     and int(a.get("consecutive_losses") or 0) == 0
                     and "losing trades in a row" in str(a.get("halt_reason") or ""))
            if stale:
                await notify(
                    f"{label}: halted on a streak that has already cleared",
                    f"`trading_halted` is true with reason "
                    f"*{a.get('halt_reason')}*, but `consecutive_losses` is 0. "
                    f"The book is taking no new entries and the condition it "
                    f"is protecting against is not present.\n\n"
                    f"Halted since {a.get('halted_at')}.",
                    severity="urgent", key=fkey3, fields={"book": label})
                self._open_findings[fkey3] = "stale_halt"
                findings.append({"finding": "stale_halt"})
            elif self._open_findings.pop(fkey3, None):
                await notify(f"{label}: halt cleared", "Trading again.",
                             severity="good", key="")

        return findings

    # Bus messages are not consumed here. The "gate shut all session"
    # question (the old invariant 4) is answered per lane by
    # ops_watchdog._check_flow() -- see G6 in the header.
    async def on_message(self, message: AgentMessage) -> list[AgentMessage]:
        return []

    # ---- small helpers ----------------------------------------------

    async def _thread(self, fn):
        import asyncio
        return await asyncio.to_thread(fn)

    async def _price(self, ticker: str, asset_type: str):
        try:
            from app.data.candles import fetch_candles_for
            pol = policy_for(asset_type)
            c = await fetch_candles_for(
                ticker, "stock" if pol.asset_type == "option" else pol.asset_type)
            return float(c[-1].close) if c else None
        except Exception:  # noqa: BLE001
            return None
