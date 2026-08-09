"""KINDRIP contribution + auto-invest engine.

Phase 9b. For each KINDRIP child whose contribution is due, this:
  1. Works out the contribution amount - a fixed dollar figure or a
     percentage of the parent's paper cash - and moves it from the
     parent's paper account into the child's account.
  2. Applies the one-time $1,000 federal seed once funding opens (the
     OBBB Future Index Account cannot be funded before 2026-07-04).
  3. Auto-invests the new cash across the child's index mix
     (SCHD / VTI / BND), keeping the cash sleeve as cash.
  4. Logs every move to kindrip_transactions with a plain-language,
     kid-friendly explanation.

Everything is modeled / paper, like the rest of Trezo.
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Optional

from app.config import get_settings
from app.kindrip.allocation import (
    KINDRIP_ETFS, resolve_mix, split_contribution,
)

FEDERAL_SEED_USD = 1000.0
FEDERAL_SEED_OPEN_DATE = date(2026, 7, 4)   # OBBB funding start date
ANNUAL_CONTRIBUTION_CAP_USD = 5000.0        # OBBB Future Index Account yearly cap


def _supabase():
    s = get_settings()
    if not s.supabase_url or not s.supabase_service_role_key:
        return None
    try:
        from supabase import create_client
        return create_client(s.supabase_url, s.supabase_service_role_key)
    except Exception:  # noqa: BLE001
        return None


def contribution_due(child: dict, today: Optional[date] = None) -> bool:
    """Is a scheduled contribution due for this child?"""
    if not child.get("contribution_enabled"):
        return False
    today = today or date.today()
    last = child.get("last_contribution_date")
    if not last:
        return True
    try:
        last_d = date.fromisoformat(str(last)[:10])
    except Exception:  # noqa: BLE001
        return True
    gap = (today - last_d).days
    return gap >= (7 if child.get("contribution_cadence") == "weekly" else 28)


def contribution_amount(child: dict, parent_cash: float) -> float:
    """The dollar contribution: a fixed amount, or a percent of parent cash.
    Never more than the parent actually has."""
    val = float(child.get("contribution_value") or 0)
    if child.get("contribution_mode") == "percent":
        amt = parent_cash * (val / 100.0)
    else:
        amt = val
    return round(max(0.0, min(amt, parent_cash)), 2)


def _etf_blurb(sym: str) -> str:
    return {
        "SCHD": "a fund of strong dividend-paying companies that send cash back to shareholders.",
        "VTI": "a fund that owns a small piece of almost every public US company.",
        "BND": "a fund of bonds - steady ballast that softens the bumps.",
    }.get(sym, "a diversified index fund.")


def child_owner_id(child: dict) -> str:
    """The PERSON this child belongs to.

    A child is a person's child, never a trading account's child. These
    were the same value while Trezo had one book per person; separating
    them (2026-08-09) means a parent can close or open books without
    orphaning their children's records.
    """
    return str(child.get("owner_id") or child.get("user_id") or "")


def child_funding_account(child: dict) -> str:
    """The BOOK the contribution is paid out of.

    Falls back to user_id so this behaves identically until the
    funding_account_key column exists. Once it does, a parent can fund
    the children from whichever account they choose.
    """
    return str(child.get("funding_account_key")
               or child.get("funding_account_id")
               or child.get("user_id") or "")


async def _parent_cash(client, parent_id: str) -> float:
    def _q():
        return (client.table("paper_accounts").select("current_cash_usd")
                .eq("user_id", parent_id).maybe_single().execute())
    try:
        res = await asyncio.to_thread(_q)
        return float((res.data or {}).get("current_cash_usd") or 0)
    except Exception:  # noqa: BLE001
        return 0.0


async def _deduct_parent_cash(client, parent_id: str, amount: float) -> None:
    cash = await _parent_cash(client, parent_id)

    def _u():
        return (client.table("paper_accounts")
                .update({"current_cash_usd": round(max(0.0, cash - amount), 2)})
                .eq("user_id", parent_id).execute())
    try:
        await asyncio.to_thread(_u)
    except Exception:  # noqa: BLE001
        pass


async def _etf_prices() -> dict:
    from app.data.candles import fetch_candles_for
    out: dict = {}
    for sym in KINDRIP_ETFS:
        try:
            candles = await fetch_candles_for(sym, "stock")
            if candles:
                out[sym] = float(candles[-1].close)
        except Exception:  # noqa: BLE001
            pass
    return out


async def _upsert_holding(client, child_id: str, symbol: str,
                          add_shares: float, add_cost: float) -> None:
    def _get():
        return (client.table("kindrip_holdings").select("*")
                .eq("child_id", child_id).eq("symbol", symbol)
                .maybe_single().execute())
    try:
        res = await asyncio.to_thread(_get)
        existing = res.data if res else None
    except Exception:  # noqa: BLE001
        existing = None

    if existing:
        new_shares = float(existing.get("shares") or 0) + add_shares
        new_cost = float(existing.get("cost_basis_usd") or 0) + add_cost

        def _u():
            return (client.table("kindrip_holdings")
                    .update({"shares": round(new_shares, 8),
                             "cost_basis_usd": round(new_cost, 2)})
                    .eq("id", existing["id"]).execute())
        try:
            await asyncio.to_thread(_u)
        except Exception:  # noqa: BLE001
            pass
    else:
        def _i():
            return (client.table("kindrip_holdings").insert({
                "child_id": child_id, "symbol": symbol,
                "shares": round(add_shares, 8),
                "cost_basis_usd": round(add_cost, 2),
            }).execute())
        try:
            await asyncio.to_thread(_i)
        except Exception:  # noqa: BLE001
            pass


async def _insert_txn(client, child_id: str, kind: str, amount: float,
                      symbol, shares, explanation: str) -> None:
    def _i():
        return client.table("kindrip_transactions").insert({
            "child_id": child_id, "kind": kind, "amount_usd": round(amount, 2),
            "symbol": symbol, "shares": shares, "explanation": explanation,
        }).execute()
    try:
        await asyncio.to_thread(_i)
    except Exception:  # noqa: BLE001
        pass


async def _ytd_contributions(client, child_id: str, today: date) -> float:
    """This calendar year's contribution total for a child.

    Only \'contribution\' rows count toward the annual cap - the one-time
    federal seed is separate and does not count against it.
    """
    year_start = date(today.year, 1, 1).isoformat()

    def _q():
        return (client.table("kindrip_transactions")
                .select("amount_usd")
                .eq("child_id", child_id)
                .eq("kind", "contribution")
                .gte("created_at", year_start)
                .execute())
    try:
        res = await asyncio.to_thread(_q)
        return round(sum(float(r.get("amount_usd") or 0)
                         for r in (res.data or [])), 2)
    except Exception:  # noqa: BLE001
        return 0.0


async def process_child(client, child: dict) -> Optional[dict]:
    """Run one child's due contribution + seed + auto-invest. Returns a
    summary dict, or None if nothing was due."""
    child_id = child["id"]
    # parent_id is the FUNDING BOOK, not the person -- see the helpers above.
    owner_id = child_owner_id(child)          # noqa: F841 (surfaced by caller)
    parent_id = child_funding_account(child)
    name = (child.get("child_name") or "your child").strip()
    today = date.today()

    txns: list[tuple] = []
    seed = 0.0
    contrib = 0.0

    # 1. Federal seed - once, on/after the OBBB funding date.
    if not child.get("federal_seed_applied") and today >= FEDERAL_SEED_OPEN_DATE:
        seed = FEDERAL_SEED_USD
        txns.append(("federal_seed", seed, None, None,
                     f"The federal government added a one-time ${seed:,.0f} "
                     f"starter gift to {name}'s Future Index Account, "
                     f"established under the One Big Beautiful Bill."))

    # 2. Scheduled contribution - if due, capped at the annual maximum.
    if contribution_due(child, today):
        desired = contribution_amount(child, await _parent_cash(client, parent_id))
        ytd = await _ytd_contributions(client, child_id, today)
        room = max(0.0, ANNUAL_CONTRIBUTION_CAP_USD - ytd)
        contrib = round(min(desired, room), 2)
        if contrib > 0:
            cadence = child.get("contribution_cadence", "monthly")
            expl = (f"Your {cadence} contribution of ${contrib:,.2f} "
                    f"was added to {name}'s account.")
            if contrib < desired:
                expl += (f" It was trimmed to stay within the "
                         f"${ANNUAL_CONTRIBUTION_CAP_USD:,.0f}-a-year limit a "
                         f"Future Index Account allows - ${ytd:,.0f} had "
                         f"already gone in during {today.year}.")
            txns.append(("contribution", contrib, None, None, expl))

    deposited = seed + contrib
    if deposited <= 0:
        return None

    # 3. Auto-invest across the child's index mix.
    mix = resolve_mix(
        child.get("allocation_mode", "auto"),
        child.get("birth_year"),
        {"schd": child.get("alloc_schd"), "vti": child.get("alloc_vti"),
         "bnd": child.get("alloc_bnd"), "cash": child.get("alloc_cash")},
    )
    legs = split_contribution(deposited, mix)
    prices = await _etf_prices()

    cash_slice = legs["cash"]
    invests: list[tuple] = []
    for sym in KINDRIP_ETFS:
        dollars = legs[sym.lower()]
        px = prices.get(sym, 0.0)
        if dollars > 0 and px > 0:
            shares = round(dollars / px, 6)
            invests.append((sym, dollars, shares))
            txns.append(("invest", dollars, sym, shares,
                          f"Bought {shares:g} shares of {sym} for ${dollars:,.2f} "
                          f"- {sym} is {_etf_blurb(sym)}"))
        else:
            cash_slice += dollars   # unpriced - hold as cash

    # 4. Persist - parent pays the contribution (the seed is free money).
    if contrib > 0:
        await _deduct_parent_cash(client, parent_id, contrib)
    for sym, dollars, shares in invests:
        await _upsert_holding(client, child_id, sym, shares, dollars)

    new_cash = float(child.get("cash_balance_usd") or 0) + cash_slice
    new_total = float(child.get("total_contributed_usd") or 0) + deposited
    upd: dict = {
        "cash_balance_usd": round(new_cash, 2),
        "total_contributed_usd": round(new_total, 2),
    }
    if seed > 0:
        upd["federal_seed_applied"] = True
    if contrib > 0:
        upd["last_contribution_date"] = today.isoformat()

    def _update_child():
        return client.table("kindrip_children").update(upd).eq("id", child_id).execute()
    try:
        await asyncio.to_thread(_update_child)
    except Exception:  # noqa: BLE001
        pass

    for kind, amount, sym, shares, expl in txns:
        await _insert_txn(client, child_id, kind, amount, sym, shares, expl)

    return {
        "child_id": child_id,
        "child_name": name,
        "seed_usd": round(seed, 2),
        "contribution_usd": round(contrib, 2),
        "deposited_usd": round(deposited, 2),
        "cash_added_usd": round(cash_slice, 2),
        "invested": [{"symbol": s, "usd": round(d, 2), "shares": sh}
                     for s, d, sh in invests],
    }
