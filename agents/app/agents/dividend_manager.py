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
from app.dividends.drip import (
    distribution_due, period_distribution, drip_explanation,
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

    async def tick(self) -> list[AgentMessage]:
        client = _supabase()
        if not client:
            return [AgentMessage(agent=self.name, kind="info",
                                 payload={"note": "Supabase not configured."})]

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
            if not distribution_due(pos, today):
                continue
            shares = float(pos.get("shares") or 0)
            if shares <= 0:
                continue

            price = await _price(pos["ticker"])
            avg_cost = float(pos.get("avg_cost") or 0)
            value = shares * price if price > 0 else shares * avg_cost
            if value <= 0:
                continue

            dist = period_distribution(value, pos.get("dist_yield_pct"))
            if dist <= 0:
                continue

            drip_on = bool(pos.get("drip_enabled", True))
            cumulative = float(pos.get("cumulative_dist") or 0) + dist
            upd: dict = {
                "last_distribution_date": today.isoformat(),
                "cumulative_dist": round(cumulative, 4),
            }
            shares_added = 0.0
            if drip_on and price > 0:
                shares_added = round(dist / price, 6)
                upd["shares"] = round(shares + shares_added, 8)

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
                    "note": drip_explanation(pos["ticker"], dist, drip_on,
                                             shares_added, price),
                },
            ))

        out.append(AgentMessage(
            agent=self.name, kind="info",
            payload={"note": "Dividend run complete",
                     "holdings": len(positions), "distributions_paid": paid},
        ))
        return out
