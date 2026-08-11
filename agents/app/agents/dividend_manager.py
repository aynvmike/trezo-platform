"""Dividend Manager Agent.

The 16th agent. Every 6 hours it walks the user's dividend holdings
(any user_positions row with a distribution yield set) and, for each one
whose weekly distribution has come due, credits a modeled distribution.

With DRIP on for that holding, the distribution buys more shares - the
position compounds. With DRIP off, it banks as cash (cumulative_dist).
Every run emits a plain-language summary.

Modeled / paper, like the rest of Trezo.
"""

from __future__ import annotations

import asyncio
from datetime import date

from app.config import get_settings
from app.dividends.schedule import latest_unpaid_ex
from app.dividends.drip import (
    distribution_due, period_distribution, drip_explanation,
    payout_frequency, periods_per_year, ex_date_price,
    total_return, yield_trap,
)

from .base import Agent, AgentMessage


def _supabase():
    s = get_settings()
    if not s.supabase_url or not s.supabase_service_role_key:
        return None
    try:
        from supabase import create_client
        return create_client(s.supabase_url, s.supabase_service_role_key)
    except Exception:  # noqa: BLE001
        return None


async def _price(ticker: str) -> float:
    """Latest modeled price for a holding. 0.0 if unavailable."""
    try:
        from app.data.candles import fetch_candles_for
        candles = await fetch_candles_for(ticker, "stock")
        return float(candles[-1].close) if candles else 0.0
    except Exception:  # noqa: BLE001
        return 0.0


class DividendManagerAgent(Agent):
    name = "dividend_manager"
    tick_interval_seconds = 21600  # every 6 hours

    _accum_day: dict = {}

    async def tick(self) -> list[AgentMessage]:
        client = _supabase()
        if not client:
            return [AgentMessage(agent=self.name, kind="info",
                                 payload={"note": "Supabase not configured."})]

        # INCOME ACCUMULATOR (2026-08-11, Mike: "we can purchase dividends
        # for holdings now we have the books"). Once per day per book, buy
        # a small tranche of the best real payer from the income pocket --
        # evidence from live ex-dates, decayer-guarded, route-checked.
        # Failure of a buy never blocks the distribution pass below.
        try:
            from datetime import date as _d
            from app.dividends.accumulator import accumulate_for_book
            def _users():
                return (client.table("paper_accounts")
                        .select("user_id").execute())
            _uids = [u["user_id"] for u in
                     ((await asyncio.to_thread(_users)).data or [])]
            _today = _d.today().isoformat()
            for _uid in _uids:
                if self._accum_day.get(_uid) == _today:
                    continue
                res = await accumulate_for_book(client, _uid)
                self._accum_day[_uid] = _today
                if res:
                    out_buy = AgentMessage(
                        agent=self.name, kind="info", confidence=1.0,
                        payload={"user_id": _uid,
                                 "event": "income_accumulate", **res})
                    try:
                        from app.runtime.bus import bus as _bus
                        await _bus.publish(out_buy)
                    except Exception:  # noqa: BLE001
                        pass
        except Exception:  # noqa: BLE001
            pass

        def _q():
            return (client.table("user_positions").select("*")
                    .gt("dist_yield_pct", 0).execute())
        try:
            positions = (await asyncio.to_thread(_q)).data or []
        except Exception as e:  # noqa: BLE001
            return [AgentMessage(agent=self.name, kind="error",
                                 payload={"error": str(e)})]

        today = date.today()
        out: list[AgentMessage] = []
        paid = 0

        for pos in positions:
            shares = float(pos.get("shares") or 0)
            if shares <= 0:
                continue

            # Real ex-date beats a modeled interval (2026-08-09). Cached
            # one call per symbol per day, and fails open to the holding's
            # declared frequency when no calendar is available.
            ex = await latest_unpaid_ex(
                pos["ticker"], pos.get("last_distribution_date"), today)
            ex_date = ex.ex_date if ex else None
            if not distribution_due(pos, today, ex_date):
                continue

            price = await _price(pos["ticker"])
            avg_cost = float(pos.get("avg_cost") or 0)
            value = shares * price if price > 0 else shares * avg_cost
            if value <= 0:
                continue

            # Frequency comes from the holding now. This used to pay every
            # holding every 7 days, which gave a quarterly payer 52
            # compounding events a year instead of 4 (2026-08-09).
            freq = payout_frequency(pos)
            if ex is not None and ex.amount > 0:
                # What the fund ACTUALLY declared beats any yield estimate.
                dist = round(ex.amount * shares, 2)
                dist_basis = f"declared ${ex.amount:.4f}/sh ({ex.source})"
            else:
                dist = period_distribution(value, pos.get("dist_yield_pct"),
                                           periods_per_year(freq))
                dist_basis = f"modeled from yield, {freq}"
            if dist <= 0:
                continue

            drip_on = bool(pos.get("drip_enabled", True))
            cumulative = float(pos.get("cumulative_dist") or 0) + dist
            upd: dict = {
                "last_distribution_date": (ex_date or today.isoformat()),
                "cumulative_dist": round(cumulative, 4),
            }
            shares_added = 0.0
            buy_price = price
            if drip_on and price > 0:
                # A real DRIP buys after the price drops by the payout.
                buy_price = ex_date_price(price, dist / shares if shares else 0.0)
                shares_added = round(dist / buy_price, 6) if buy_price > 0 else 0.0
                upd["shares"] = round(shares + shares_added, 8)

            # Total return is the only honest score for an income holding:
            # yield alone cannot say whether the position made money.
            tr = total_return(shares + shares_added, price,
                              float(pos.get("avg_cost") or 0), cumulative)
            warning = yield_trap(tr)

            def _update(pid=pos["id"], u=upd):
                return (client.table("user_positions").update(u)
                        .eq("id", pid).execute())
            try:
                await asyncio.to_thread(_update)
            except Exception as e:  # noqa: BLE001
                out.append(AgentMessage(agent=self.name, kind="error",
                                        payload={"ticker": pos.get("ticker"),
                                                 "error": str(e)}))
                continue

            paid += 1
            out.append(AgentMessage(
                agent=self.name, kind="info", confidence=1.0,
                payload={
                    "user_id": pos.get("user_id"),
                    "event": "dividend_distribution",
                    "ticker": pos["ticker"],
                    "distribution_usd": dist,
                    "drip": drip_on,
                    "shares_added": shares_added,
                    "frequency": freq,
                    "ex_date": ex_date or "",
                    "basis": dist_basis,
                    "total_return_pct": tr["total_return_pct"],
                    "income_return_pct": tr["income_return_pct"],
                    "price_return_pct": tr["price_return_pct"],
                    "yield_trap": bool(warning),
                    "warning": warning or "",
                    "note": drip_explanation(pos["ticker"], dist, drip_on,
                                             shares_added, buy_price, freq),
                },
            ))

        out.append(AgentMessage(
            agent=self.name, kind="info",
            payload={"note": "Dividend run complete",
                     "holdings": len(positions), "distributions_paid": paid},
        ))
        return out
