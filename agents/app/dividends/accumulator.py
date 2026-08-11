"""Income accumulator -- the agents BUY dividend holdings, per book.

WHY (Mike, 2026-08-11): "we can purchase dividends for holdings now we
have the books... we need to focus on generating wealth for our platform
users." The dividend engine could PAY distributions and score total
return, but nothing ever ACQUIRED a holding -- 8 of 10 dividend rows had
zero shares, so the income layer idled while its pocket sat funded.

WHAT IT DOES, once per day per book, inside dividend_manager's tick:
  1. Budget: the book's INCOME pocket (build_allocation, so posture and
     user overrides apply) minus income capital already deployed
     (wheel collateral shares this pocket). A small daily tranche only --
     accumulation is DCA, not a lump.
  2. Candidates: the Wheel bench income names (Tiers A-C -- real payers).
  3. Evidence per name, all from live data, nothing hardcoded:
       - trailing yield derived from REAL ex-dividend history
         (schedule.ex_dividend_history -- Finnhub, Alpha Vantage fallback)
         and the live price;
       - payout frequency derived from the actual ex-date spacing --
         which also fixes the "everything defaults to quarterly" gap;
       - DECAYER GUARD: names bleeding worse than -2%/month
         (wheel.decay_rate_monthly, the AIYY lesson) are skipped unless
         the yield is at least 2x the annualized decay. Total-return
         thinking at BUY time, not just at scoring time.
  4. Buys the best candidate as a notional market order on THIS book's
     broker account (route-guard checked), then upserts the
     user_positions row so dividend_manager starts paying and scoring it
     (DRIP on).
  5. Caps: per-name at 25% of the income budget; skips books whose
     pocket is under $500 (the primary's $385 pocket stays untouched --
     no forced dust positions).

Every decision is activity-logged as income_accumulate. Fails open
everywhere: no data, no candidates, market closed -> log and wait for
the next tick. Nothing here raises into the agent loop.
"""

from __future__ import annotations

import asyncio
import dataclasses
from datetime import date, datetime, timezone
from typing import Optional

# Real income payers from the Wheel bench (Tiers A-C).
INCOME_BENCH = ["O", "MAIN", "STAG", "NLY", "ARCC",
                "F", "T", "KMI", "VZ", "MO",
                "PFE", "KHC", "CSCO", "BMY", "KEY", "HPQ", "AGNC"]

MIN_POCKET_USD = 500.0      # below this, a book doesn't accumulate
TRANCHE_PCT = 0.10          # of the income budget, per day
TRANCHE_MAX_USD = 2500.0
TRANCHE_MIN_USD = 200.0
PER_NAME_CAP_PCT = 0.25     # of the income budget, per name
DECAYER_MONTHLY = -0.02     # from the wheel: -2%/mo trailing = decayer


def _rec(event: str, ticker: str, reason: str, user_id: str) -> None:
    try:
        from app.agents.activity_log import record
        record(event, ticker, reason=reason[:290],
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
            da = date.fromisoformat(str(a)[:10])
            db = date.fromisoformat(str(b)[:10])
            gaps.append(abs((da - db).days))
        med = sorted(gaps)[len(gaps) // 2]
    except Exception:  # noqa: BLE001
        return "quarterly"
    if med <= 10:  return "weekly"
    if med <= 20:  return "biweekly"
    if med <= 45:  return "monthly"
    if med <= 135: return "quarterly"
    if med <= 250: return "semiannual"
    return "annual"


async def evaluate_candidate(sym: str) -> Optional[dict]:
    """Yield + frequency + decay for one name, all from live data."""
    try:
        from app.dividends.schedule import ex_dividend_history
        from app.data.candles import fetch_candles_for
        rows = await ex_dividend_history(sym)
        if not rows:
            return None
        candles = await fetch_candles_for(sym, "stock")
        if not candles:
            return None
        price = float(candles[-1].close)
        if price <= 0:
            return None
        freq = derive_frequency([r.ex_date for r in rows])
        from app.dividends.drip import periods_per_year
        n = periods_per_year(freq)
        recent = [r.amount for r in rows[:max(2, min(4, n))] if r.amount > 0]
        if not recent:
            return None
        per_share = sum(recent) / len(recent)
        annual = per_share * n
        yield_pct = annual / price * 100.0
        # Decayer guard (the AIYY lesson, applied at BUY time).
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
                    f"decayer: {decay*100:.1f}%/mo (~{annual_decay_pct:.0f}%/yr) "
                    f"vs yield {yield_pct:.1f}% -- payout wouldn't outrun the bleed")}
        return {"symbol": sym, "price": round(price, 4),
                "yield_pct": round(yield_pct, 2), "frequency": freq,
                "per_share": round(per_share, 4)}
    except Exception:  # noqa: BLE001
        return None


async def accumulate_for_book(client, user_id: str) -> Optional[dict]:
    """One buy decision for one book. Returns a summary dict or None."""
    from app.brokers.accounts import (
        account_for_user, bind_for_user, multi_account_active)
    from app.brokers.route_guard import check_route
    from app.runtime.settings import get_bot_settings
    from app.paper.allocation import build_allocation, effective_equity

    acct = account_for_user(user_id) if multi_account_active() else None
    eq = await effective_equity(user_id)
    if eq <= 0:
        return None
    bs = get_bot_settings(user_id)
    plan = build_allocation(eq, posture_setting=bs.account_posture,
                            overrides=bs.allocation_overrides)
    d = dataclasses.asdict(plan) if dataclasses.is_dataclass(plan) else vars(plan)
    income_budget = float((d.get("budgets") or {}).get("income") or 0)
    if income_budget < MIN_POCKET_USD:
        return None  # book too small to accumulate -- no dust positions

    # Free budget = pocket minus income capital already working (wheel
    # collateral + existing holdings at cost).
    deployed = 0.0
    try:
        from app.paper.allocation import deployed_capital
        deployed = float((await deployed_capital(user_id)).get("income") or 0)
    except Exception:  # noqa: BLE001
        pass
    def _held():
        return (client.table("user_positions")
                .select("ticker, shares, avg_cost")
                .eq("user_id", user_id).execute())
    held_rows = (await asyncio.to_thread(_held)).data or []
    held_cost = {str(r["ticker"]).upper():
                 float(r.get("shares") or 0) * float(r.get("avg_cost") or 0)
                 for r in held_rows}
    free = income_budget - deployed - sum(held_cost.values())
    tranche = min(TRANCHE_PCT * income_budget, TRANCHE_MAX_USD, free)
    if tranche < TRANCHE_MIN_USD:
        _rec("income_accumulate", "BENCH",
             f"skipped: income pocket ${income_budget:,.0f}, free ${free:,.0f} "
             f"below the ${TRANCHE_MIN_USD:.0f} tranche floor", user_id)
        return None

    # Best candidate not already at its per-name cap.
    per_name_cap = PER_NAME_CAP_PCT * income_budget
    best = None
    for sym in INCOME_BENCH:
        if held_cost.get(sym, 0.0) >= per_name_cap:
            continue
        ev = await evaluate_candidate(sym)
        if ev is None:
            continue
        if ev.get("skip"):
            _rec("income_accumulate", sym, f"candidate skipped: {ev['skip']}",
                 user_id)
            continue
        if best is None or ev["yield_pct"] > best["yield_pct"]:
            best = ev
    if best is None:
        _rec("income_accumulate", "BENCH",
             "no eligible candidate (no data, all decayers, or all at cap)",
             user_id)
        return None

    # Buy: notional market order on THIS book's broker account.
    notional = round(min(tranche, per_name_cap - held_cost.get(best["symbol"], 0.0)), 2)
    filled_shares = 0.0
    with bind_for_user(user_id):
        ok, note = check_route(user_id)
        if not ok:
            _rec("route_mismatch", best["symbol"], f"[income_accumulate] {note}",
                 user_id)
            return None
        try:
            from app.brokers.alpaca import _post  # same door every order uses
            order = await _post("/v2/orders", {
                "symbol": best["symbol"], "notional": str(notional),
                "side": "buy", "type": "market", "time_in_force": "day",
            })
            if not order or order.get("id") is None:
                raise RuntimeError(f"order not accepted: {order}")
            # Poll once for the fill so the row records real shares.
            import json as _j, urllib.request as _u  # noqa: E401
            await asyncio.sleep(3)
            from app.brokers.accounts import current_account
            a = current_account()
            req = _u.Request(f"{a.base_url}/v2/orders/{order['id']}",
                             headers=a.headers())
            od = _j.load(_u.urlopen(req, timeout=15))
            filled_shares = float(od.get("filled_qty") or 0)
            fill_price = float(od.get("filled_avg_price") or best["price"])
            if filled_shares <= 0:
                _rec("income_accumulate", best["symbol"],
                     f"order {od.get('status')}: no fill yet (${notional}); "
                     f"row deferred to next tick", user_id)
                return None
        except Exception as e:  # noqa: BLE001
            _rec("income_accumulate", best["symbol"],
                 f"buy failed: {str(e)[:120]}", user_id)
            return None

    # Record the holding so dividend_manager pays and scores it.
    prev = next((r for r in held_rows
                 if str(r["ticker"]).upper() == best["symbol"]), None)
    def _upsert():
        if prev is not None:
            old_sh = float(prev.get("shares") or 0)
            old_c = float(prev.get("avg_cost") or 0)
            new_sh = old_sh + filled_shares
            new_cost = ((old_sh * old_c + filled_shares * fill_price) / new_sh
                        if new_sh > 0 else fill_price)
            return (client.table("user_positions")
                    .update({"shares": round(new_sh, 6),
                             "avg_cost": round(new_cost, 4),
                             "dist_yield_pct": best["yield_pct"]})
                    .eq("user_id", user_id)
                    .eq("ticker", best["symbol"]).execute())
        return (client.table("user_positions").insert({
            "user_id": user_id, "ticker": best["symbol"],
            "asset_type": "stock",
            "shares": round(filled_shares, 6),
            "avg_cost": round(fill_price, 4),
            "dist_yield_pct": best["yield_pct"],
            "drip_enabled": True, "cumulative_dist": 0,
            "notes": (f"income accumulator {date.today().isoformat()}: "
                      f"yield {best['yield_pct']}% ({best['frequency']}, "
                      f"derived from real ex-dates)"),
        }).execute())
    try:
        await asyncio.to_thread(_upsert)
    except Exception as e:  # noqa: BLE001
        _rec("income_accumulate", best["symbol"],
             f"BOUGHT {filled_shares} @ {fill_price} but row write failed: "
             f"{str(e)[:100]} -- reconcile will catch it", user_id)
    _rec("income_accumulate", best["symbol"],
         f"bought ${notional} (~{filled_shares} sh @ {fill_price}) -- "
         f"yield {best['yield_pct']}% {best['frequency']}, DRIP on, "
         f"income pocket ${income_budget:,.0f}", user_id)
    return {"symbol": best["symbol"], "notional": notional,
            "shares": filled_shares, "yield_pct": best["yield_pct"],
            "frequency": best["frequency"]}
