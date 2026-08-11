"""Income accumulator v2 -- the Dividends (Long-Term) sleeve, per book.

Implements the DIVIDEND_LT_STRATEGY v1 spec (drop-box:
qc--DIVIDEND_LT_STRATEGY_v1.md) as THE strategy of each book's income
pocket. Mike, 2026-08-11: run it on BOTH big books, remove nothing --
so this is not a posture conversion. The sleeve is the income pocket,
whatever the pocket's size: $7,500 on the 25k book, $18,750 on the 75k,
inactive under $500 (the primary's $385 stays untouched).

THE SPEC, MAPPED
- Tiers + target weights (spec 3): 40% index-premium, 30% dividend
  growth, 20% single payers (= the Wheel bench), 10% cash buffer.
- Routing rule (spec 4.3): each daily tranche goes to the MOST
  UNDERWEIGHT tier vs those targets; within the tier, best evidence.
- Health screen (spec 2): trailing payout must not exceed trailing
  total return -- the recycling-ratio invariant applied at BUY time.
  A holding paying out more than it earns is liquidating principal,
  whatever the headline yield says. AUM and reverse-split screens are
  NOT implemented (no wired data source) -- named gap, not silent.
- No auto-DRIP (spec 4.3): new holdings are recorded drip_enabled=False.
  Distributions bank as cash; banked cash raises equity, equity raises
  the pocket, and the ROUTER decides where it goes -- never mechanically
  back into the payer.
- Caps (spec 3): 10% of the sleeve per holding; 25% per factor, with
  the REIT/BDC cluster counted as ONE factor (the 6.83-effective-bets
  lesson).
- Decayer guard kept from v1 (the AIYY lesson at buy time).

Still v1-scope elsewhere: the payment forecaster + MAPE, the
ACCUMULATE/INCOME mode switch, and the ex-div-aware kill-switch are
separate builds (spec 4.1, 5, 7). Until the kill-switch learns ex-div
mechanics, tranche sizes here stay small by design.

Fails open everywhere; every decision is activity-logged
income_accumulate. Nothing raises into the agent loop.
"""

from __future__ import annotations

import asyncio
import dataclasses
from datetime import date
from typing import Optional

# ---- the sleeve's universe (spec 2) ----------------------------------
# Candidates only -- every buy still passes the evidence gates below.
TIERS: dict[str, dict] = {
    "index_premium": {
        "target": 0.40,
        "symbols": ["JEPQ", "JEPI", "QYLD", "XDTE", "SPYI"],
    },
    "growth": {
        "target": 0.30,
        "symbols": ["SCHD", "VIG", "DGRO"],
    },
    "single_payers": {
        "target": 0.20,
        # The Wheel bench income names (Tiers A-C) -- the same list the
        # Wheel's CSP acquisition engine works, so assignment lands in
        # names this sleeve wants anyway (spec 3).
        "symbols": ["O", "MAIN", "STAG", "NLY", "ARCC",
                     "F", "T", "KMI", "VZ", "MO",
                     "PFE", "KHC", "CSCO", "BMY", "KEY", "HPQ", "AGNC"],
    },
    "buffer": {
        "target": 0.10,
        "symbols": ["SGOV", "BIL"],
    },
}

# REIT/BDC is ONE factor (spec 3). Everything else counts as itself.
REIT_BDC = {"O", "MAIN", "STAG", "NLY", "ARCC", "AGNC", "PSEC"}
FACTOR_CAP_PCT = 0.25
PER_NAME_CAP_PCT = 0.10

MIN_POCKET_USD = 500.0
TRANCHE_PCT = 0.10
TRANCHE_MAX_USD = 2500.0
TRANCHE_MIN_USD = 200.0
DECAYER_MONTHLY = -0.02


def _rec(ticker: str, reason: str, user_id: str) -> None:
    try:
        from app.agents.activity_log import record
        record("income_accumulate", ticker, reason=reason[:290],
               extra={"user_id": str(user_id or "")})
    except Exception:  # noqa: BLE001
        pass


def derive_frequency(ex_dates: list[str]) -> str:
    """Payout cadence from actual ex-date spacing. Conservative default."""
    ds = sorted(ex_dates, reverse=True)[:6]
    if len(ds) < 2:
        return "quarterly"
    try:
        gaps = []
        for a, b in zip(ds, ds[1:]):
            gaps.append(abs((date.fromisoformat(str(a)[:10])
                             - date.fromisoformat(str(b)[:10])).days))
        med = sorted(gaps)[len(gaps) // 2]
    except Exception:  # noqa: BLE001
        return "quarterly"
    if med <= 10:  return "weekly"
    if med <= 20:  return "biweekly"
    if med <= 45:  return "monthly"
    if med <= 135: return "quarterly"
    if med <= 250: return "semiannual"
    return "annual"


def tier_of(symbol: str) -> Optional[str]:
    for name, t in TIERS.items():
        if symbol.upper() in t["symbols"]:
            return name
    return None


def factor_of(symbol: str) -> str:
    return "reit_bdc" if symbol.upper() in REIT_BDC else symbol.upper()


async def evaluate_candidate(sym: str) -> Optional[dict]:
    """Evidence for one name, all live data: derived yield + frequency,
    decayer guard, and the spec-2 health screen (trailing payout <=
    trailing total return over ~6 months)."""
    try:
        from app.dividends.schedule import ex_dividend_history
        from app.data.candles import fetch_candles_for
        rows = await ex_dividend_history(sym)
        if not rows:
            return None
        candles = await fetch_candles_for(sym, "stock")
        if not candles or len(candles) < 30:
            return None
        price = float(candles[-1].close)
        if price <= 0:
            return None
        freq = derive_frequency([r.ex_date for r in rows])
        from app.dividends.drip import periods_per_year
        n = periods_per_year(freq)
        recent = [r.amount for r in rows[:max(2, min(6, n))] if r.amount > 0]
        if not recent:
            return None
        per_share = sum(recent) / len(recent)
        annual = per_share * n
        yield_pct = annual / price * 100.0

        # Decayer guard (v1, kept).
        decay = 0.0
        try:
            from app.strategies.wheel import decay_rate_monthly
            decay = float(decay_rate_monthly(candles) or 0.0)
        except Exception:  # noqa: BLE001
            decay = 0.0
        if decay <= DECAYER_MONTHLY:
            annual_decay_pct = abs(decay) * 12.0 * 100.0
            if yield_pct < 2.0 * annual_decay_pct:
                return {"symbol": sym, "skip": (
                    f"decayer {decay*100:.1f}%/mo vs yield {yield_pct:.1f}% "
                    f"-- payout wouldn't outrun the bleed")}

        # Spec-2 health screen: trailing ~6mo payout vs total return.
        # payout rate is % of NAV -> decay is a rate, not an event.
        try:
            lookback = min(len(candles) - 1, 126)
            past = float(candles[-1 - lookback].close)
            cutoff = (date.today().toordinal() - 183)
            paid = sum(r.amount for r in rows
                       if date.fromisoformat(r.ex_date).toordinal() >= cutoff
                       and r.amount > 0)
            if past > 0 and paid > 0:
                tr_6mo = (price - past) + paid          # per share
                if paid > tr_6mo:
                    return {"symbol": sym, "skip": (
                        f"health screen: paid ${paid:.2f}/sh over ~6mo but "
                        f"total return was ${tr_6mo:.2f}/sh -- recycling "
                        f"ratio > 1, liquidating principal")}
        except Exception:  # noqa: BLE001
            pass

        return {"symbol": sym, "price": round(price, 4),
                "yield_pct": round(yield_pct, 2), "frequency": freq}
    except Exception:  # noqa: BLE001
        return None


async def accumulate_for_book(client, user_id: str) -> Optional[dict]:
    """One routed buy for one book: tranche -> most-underweight tier ->
    best evidence candidate -> notional order on THIS book's broker."""
    from app.brokers.accounts import (
        account_for_user, bind_for_user, multi_account_active)
    from app.brokers.route_guard import check_route
    from app.runtime.settings import get_bot_settings
    from app.paper.allocation import build_allocation, effective_equity

    eq = await effective_equity(user_id)
    if eq <= 0:
        return None
    bs = get_bot_settings(user_id)
    plan = build_allocation(eq, posture_setting=bs.account_posture,
                            overrides=bs.allocation_overrides)
    d = dataclasses.asdict(plan) if dataclasses.is_dataclass(plan) else vars(plan)
    sleeve = float((d.get("budgets") or {}).get("income") or 0)
    if sleeve < MIN_POCKET_USD:
        return None

    # Current sleeve holdings at cost, from the ledger.
    def _held():
        return (client.table("user_positions")
                .select("ticker, shares, avg_cost")
                .eq("user_id", user_id).execute())
    held_rows = (await asyncio.to_thread(_held)).data or []
    held_cost: dict[str, float] = {}
    for r in held_rows:
        tk = str(r["ticker"]).upper()
        held_cost[tk] = (held_cost.get(tk, 0.0)
                         + float(r.get("shares") or 0)
                         * float(r.get("avg_cost") or 0))

    # Wheel collateral shares the pocket (spec 3: the Wheel is this
    # sleeve's acquisition engine, not a competitor).
    deployed_income = 0.0
    try:
        from app.paper.allocation import deployed_capital
        deployed_income = float(
            (await deployed_capital(user_id)).get("income") or 0)
    except Exception:  # noqa: BLE001
        pass
    sleeve_used = sum(v for k, v in held_cost.items() if tier_of(k))
    # INITIAL DEPLOYMENT target (Mike 2026-08-11): the sleeve spends up
    # to this milestone, then stops tranche buys -- while the pocket
    # itself keeps its posture size and keeps growing with the book.
    # 0 / unset = no cap. Keyed by account slot via the registry.
    target = sleeve
    try:
        from app.config import get_settings as _gs
        from app.brokers.accounts import account_for_user as _afu
        _acct = _afu(user_id)
        _slot = {"acct2": "trezo_divlt_target_2",
                 "acct3": "trezo_divlt_target_3"}.get(
                     getattr(_acct, "account_id", ""))
        if _slot:
            _tv = float(getattr(_gs(), _slot, 0) or 0)
            if _tv > 0:
                target = min(sleeve, _tv)
    except Exception:  # noqa: BLE001
        pass
    if sleeve_used >= target:
        _rec("SLEEVE", f"deployment target reached: ${sleeve_used:,.0f} of "
                       f"${target:,.0f} invested -- holding, not buying",
             user_id)
        return None
    free = min(sleeve - deployed_income - sleeve_used,
               target - sleeve_used)
    tranche = min(TRANCHE_PCT * sleeve, TRANCHE_MAX_USD, free)
    if tranche < TRANCHE_MIN_USD:
        _rec("SLEEVE", f"skipped: sleeve ${sleeve:,.0f}, free ${free:,.0f} "
                       f"under the ${TRANCHE_MIN_USD:.0f} floor", user_id)
        return None

    # Most-underweight tier first (spec 4.3).
    def _tier_weight(name: str) -> float:
        cost = sum(v for k, v in held_cost.items() if tier_of(k) == name)
        return cost / sleeve if sleeve > 0 else 0.0
    order = sorted(TIERS, key=lambda n: _tier_weight(n) - TIERS[n]["target"])

    per_name_cap = PER_NAME_CAP_PCT * sleeve
    factor_used: dict[str, float] = {}
    for k, v in held_cost.items():
        if tier_of(k):
            factor_used[factor_of(k)] = factor_used.get(factor_of(k), 0.0) + v

    best, best_tier = None, None
    for tier_name in order:
        for sym in TIERS[tier_name]["symbols"]:
            if held_cost.get(sym, 0.0) >= per_name_cap:
                continue
            if (factor_used.get(factor_of(sym), 0.0)
                    >= FACTOR_CAP_PCT * sleeve):
                continue
            ev = await evaluate_candidate(sym)
            if ev is None:
                continue
            if ev.get("skip"):
                _rec(sym, f"candidate skipped: {ev['skip']}", user_id)
                continue
            if best is None or ev["yield_pct"] > best["yield_pct"]:
                best, best_tier = ev, tier_name
        if best is not None:
            break  # stay in the most-underweight tier once it has a name
    if best is None:
        _rec("SLEEVE", "no eligible candidate in any tier "
                       "(no data, decayers, health-screen fails, or caps)",
             user_id)
        return None

    room = per_name_cap - held_cost.get(best["symbol"], 0.0)
    notional = round(max(0.0, min(tranche, room)), 2)
    if notional < TRANCHE_MIN_USD:
        _rec(best["symbol"], f"skipped: only ${notional:.0f} of room under "
                             f"the per-name cap", user_id)
        return None

    filled_shares, fill_price = 0.0, float(best["price"])
    with bind_for_user(user_id):
        ok, note = check_route(user_id)
        if not ok:
            _rec(best["symbol"], f"route check failed: {note}", user_id)
            return None
        try:
            from app.brokers.alpaca import _post
            order_r = await _post("/v2/orders", {
                "symbol": best["symbol"], "notional": str(notional),
                "side": "buy", "type": "market", "time_in_force": "day",
            })
            if not order_r or order_r.get("id") is None:
                raise RuntimeError(f"order not accepted: {order_r}")
            import json as _j, urllib.request as _u  # noqa: E401
            await asyncio.sleep(3)
            from app.brokers.accounts import current_account
            a = current_account()
            req = _u.Request(f"{a.base_url}/v2/orders/{order_r['id']}",
                             headers=a.headers())
            od = _j.load(_u.urlopen(req, timeout=15))
            filled_shares = float(od.get("filled_qty") or 0)
            fill_price = float(od.get("filled_avg_price") or best["price"])
            if filled_shares <= 0:
                _rec(best["symbol"],
                     f"order {od.get('status')}: no fill yet (${notional}) "
                     f"-- deferred to next tick", user_id)
                return None
        except Exception as e:  # noqa: BLE001
            _rec(best["symbol"], f"buy failed: {str(e)[:120]}", user_id)
            return None

    prev = next((r for r in held_rows
                 if str(r["ticker"]).upper() == best["symbol"]), None)
    def _upsert():
        if prev is not None:
            old_sh = float(prev.get("shares") or 0)
            old_c = float(prev.get("avg_cost") or 0)
            new_sh = old_sh + filled_shares
            new_c = ((old_sh * old_c + filled_shares * fill_price) / new_sh
                     if new_sh > 0 else fill_price)
            return (client.table("user_positions")
                    .update({"shares": round(new_sh, 6),
                             "avg_cost": round(new_c, 4),
                             "dist_yield_pct": best["yield_pct"],
                             "drip_enabled": False})
                    .eq("user_id", user_id)
                    .eq("ticker", best["symbol"]).execute())
        return (client.table("user_positions").insert({
            "user_id": user_id, "ticker": best["symbol"],
            "asset_type": "stock",
            "shares": round(filled_shares, 6),
            "avg_cost": round(fill_price, 4),
            "dist_yield_pct": best["yield_pct"],
            # Spec 4.3: never auto-DRIP into the payer. Cash banks; the
            # ROUTER decides where it compounds.
            "drip_enabled": False, "cumulative_dist": 0,
            "notes": (f"DIV-LT sleeve {date.today().isoformat()} "
                      f"[{best_tier}] yield {best['yield_pct']}% "
                      f"({best['frequency']}, from real ex-dates)"),
        }).execute())
    try:
        await asyncio.to_thread(_upsert)
    except Exception as e:  # noqa: BLE001
        _rec(best["symbol"],
             f"BOUGHT {filled_shares} @ {fill_price} but row write failed: "
             f"{str(e)[:100]} -- reconcile will catch it", user_id)
    _rec(best["symbol"],
         f"[{best_tier}] bought ${notional} (~{filled_shares} sh @ "
         f"{fill_price}) yield {best['yield_pct']}% {best['frequency']}, "
         f"no-DRIP (router compounds), sleeve ${sleeve:,.0f}", user_id)
    return {"symbol": best["symbol"], "tier": best_tier,
            "notional": notional, "shares": filled_shares,
            "yield_pct": best["yield_pct"], "frequency": best["frequency"]}
