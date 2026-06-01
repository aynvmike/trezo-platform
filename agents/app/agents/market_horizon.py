"""Market Horizon Agent.

Trezo's specialist scanners hunt within their own universes. Market
Horizon zooms out: every 15 minutes it takes the pulse of six asset
classes (stocks, crypto, gold, the dollar, bonds, income ETFs) and
emits an info message summarising the cross-asset state - which class
leads, which lags, and whether classic correlations (gold/dollar,
crypto/dollar, bonds/stocks) are intact.

It exists so the user is not confined to a watchlist view of the world.
The same compute_snapshot() helper backs the /markets/pulse endpoint
the Market Horizons page renders.
"""

from __future__ import annotations

from .base import Agent, AgentMessage
from app.data.markets_horizon import compute_snapshot, summarise_snapshot


class MarketHorizonAgent(Agent):
    name = "market_horizon"
    tick_interval_seconds = 900  # 15 minutes

    async def tick(self) -> list[AgentMessage]:
        try:
            snap = await compute_snapshot()
        except Exception as e:  # noqa: BLE001
            return [AgentMessage(
                agent=self.name, kind="error",
                payload={"error": f"Cross-asset snapshot failed: {e}"},
            )]
        if not snap.get("assets"):
            return [AgentMessage(
                agent=self.name, kind="info",
                payload={"note": "Market Horizon - no feeds available right now."},
            )]
        return [AgentMessage(
            agent=self.name, kind="info",
            confidence=min(len(snap["assets"]) / 6.0, 1.0),
            payload={"note": summarise_snapshot(snap), "snapshot": snap},
        )]
