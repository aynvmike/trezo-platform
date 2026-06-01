"""Strategy Discovery Agent.

Phase 8g - activated (was a Phase 5 stub). Every hour it computes the
performance report - win rate, profit factor, expectancy, per-strategy
breakdown, worst drawdown - for each paper account and emits it. At every
25-trade milestone it flags that a review is due, per the document's
feedback loop (TREZO_NOVA_BOT_TRADE_RULES.md Section 11).
"""

from __future__ import annotations

import asyncio

from app.config import get_settings
from app.paper.performance import performance_for_user

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


class StrategyDiscoveryAgent(Agent):
    name = "strategy_discovery"
    tick_interval_seconds = 3600  # hourly

    async def tick(self) -> list[AgentMessage]:
        client = _supabase()
        if not client:
            return [AgentMessage(agent=self.name, kind="info",
                                 payload={"note": "Supabase not configured."})]

        def _users():
            return client.table("paper_accounts").select("user_id").execute()

        try:
            users = [u["user_id"] for u in ((await asyncio.to_thread(_users)).data or [])]
        except Exception as e:  # noqa: BLE001
            return [AgentMessage(agent=self.name, kind="error", payload={"error": str(e)})]

        out: list[AgentMessage] = []
        for uid in users:
            rep = await performance_for_user(client, uid)

            # With enough history, flag the weakest strategy as a refinement hint.
            weakest = None
            if rep.total_trades >= 10 and rep.by_strategy:
                worst = min(rep.by_strategy, key=lambda s: s["total_pnl_usd"])
                if worst["total_pnl_usd"] < 0:
                    weakest = worst["strategy"]

            out.append(AgentMessage(
                agent=self.name,
                kind="metrics",
                confidence=min(rep.total_trades / 100.0, 1.0),
                payload={
                    "user_id": uid,
                    "note": "Performance report",
                    "total_trades": rep.total_trades,
                    "win_rate": rep.win_rate,
                    "profit_factor": rep.profit_factor,
                    "expectancy_usd": rep.expectancy_usd,
                    "total_realized_usd": rep.total_realized_usd,
                    "max_drawdown_usd": rep.max_drawdown_usd,
                    "by_strategy": rep.by_strategy,
                    "review_due": rep.review_due,
                    "weakest_strategy": weakest,
                },
            ))
            if rep.review_due:
                out.append(AgentMessage(
                    agent=self.name, kind="alert",
                    payload={"user_id": uid, "event": "performance_review_due",
                             "note": f"{rep.total_trades} trades logged - time for a 25-trade review"},
                ))

        if not out:
            out.append(AgentMessage(agent=self.name, kind="info",
                                    payload={"note": "No paper accounts to analyze."}))

        # Phase 13 — turn this run into durable shared memory other agents
        # can read, and learn from the backtest log (the Phase 12d substrate).
        try:
            prior = await self.recall(shared=True, limit=10)
        except Exception:  # noqa: BLE001
            prior = []
        for msg in list(out):
            payload = msg.payload if isinstance(msg.payload, dict) else {}
            weak = payload.get("weakest_strategy")
            if weak:
                await self.remember(
                    topic=f"weak_strategy:{weak}",
                    content=(f"The {weak} strategy is running at a net loss in "
                             f"paper trading - a refinement candidate."),
                    category="warning")
        insight = await self._backtest_insight(client)
        if insight:
            await self.remember(topic="backtest_leader", content=insight)
        out.append(AgentMessage(
            agent=self.name, kind="info",
            payload={"note": "Shared agent memory updated",
                     "prior_memory_recalled": len(prior)}))
        return out

    async def _backtest_insight(self, client) -> str:
        """Read the backtest_runs log and summarise the standout strategy."""
        def _q():
            return (client.table("backtest_runs")
                    .select("strategy, total_return_pct, trades")
                    .order("created_at", desc=True).limit(200).execute()).data or []
        try:
            rows = await asyncio.to_thread(_q)
        except Exception:  # noqa: BLE001
            return ""
        agg: dict[str, list[float]] = {}
        for r in rows:
            if (r.get("trades") or 0) <= 0:
                continue
            agg.setdefault(str(r.get("strategy") or "default"), []).append(
                float(r.get("total_return_pct") or 0.0))
        means = {s: sum(v) / len(v) for s, v in agg.items() if v}
        if not means:
            return ""
        best = max(means, key=lambda k: means[k])
        total = sum(len(v) for v in agg.values())
        return (f"Across {total} backtests, the '{best}' strategy shows the "
                f"strongest average return ({means[best]:+.1f}%).")
