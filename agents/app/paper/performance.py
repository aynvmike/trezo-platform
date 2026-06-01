"""Performance metrics + the feedback loop.

Phase 8g, from TREZO_NOVA_BOT_TRADE_RULES.md Section 11. Reads closed
paper positions and computes the numbers a trader reviews: win rate,
average win and loss, profit factor, expectancy, total realized P&L, the
worst drawdown, and a per-strategy breakdown.

The Strategy Discovery agent calls this on a schedule and emits the
report so the dashboard and the activity feed can show it.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, asdict, field

REVIEW_EVERY = 25   # the document reviews performance every 25 trades


@dataclass
class StrategyStat:
    strategy: str
    trades: int
    wins: int
    win_rate: float
    total_pnl_usd: float


@dataclass
class PerformanceReport:
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    avg_win_usd: float = 0.0
    avg_loss_usd: float = 0.0
    profit_factor: float = 0.0
    expectancy_usd: float = 0.0
    total_realized_usd: float = 0.0
    max_drawdown_usd: float = 0.0
    by_strategy: list = field(default_factory=list)
    review_due: bool = False
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def compute_performance(positions: list) -> PerformanceReport:
    """Compute metrics from a list of closed paper_positions rows."""
    closed: list[tuple[str, float]] = []
    for p in positions:
        pnl = p.get("realized_pnl_usd")
        if pnl is None:
            continue
        try:
            closed.append((str(p.get("strategy") or "default"), float(pnl)))
        except (TypeError, ValueError):
            continue

    n = len(closed)
    if n == 0:
        return PerformanceReport(note="No closed trades yet.")

    pnls = [x[1] for x in closed]
    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    total = sum(pnls)

    # Max drawdown of the cumulative realized-P&L curve.
    cum = peak = max_dd = 0.0
    for x in pnls:
        cum += x
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)

    # Per-strategy breakdown.
    by_strat: dict[str, list] = {}
    for strat, pnl in closed:
        by_strat.setdefault(strat, []).append(pnl)
    strat_stats = []
    for strat, ps in sorted(by_strat.items()):
        w = sum(1 for x in ps if x > 0)
        strat_stats.append(StrategyStat(
            strategy=strat, trades=len(ps), wins=w,
            win_rate=round(w / len(ps), 3),
            total_pnl_usd=round(sum(ps), 2),
        ))

    if gross_loss > 0:
        profit_factor = round(gross_profit / gross_loss, 2)
    else:
        profit_factor = 999.0 if gross_profit > 0 else 0.0

    return PerformanceReport(
        total_trades=n,
        wins=len(wins),
        losses=len(losses),
        win_rate=round(len(wins) / n, 3),
        avg_win_usd=round(gross_profit / len(wins), 2) if wins else 0.0,
        avg_loss_usd=round(gross_loss / len(losses), 2) if losses else 0.0,
        profit_factor=profit_factor,
        expectancy_usd=round(total / n, 2),
        total_realized_usd=round(total, 2),
        max_drawdown_usd=round(max_dd, 2),
        by_strategy=[asdict(s) for s in strat_stats],
        review_due=(n % REVIEW_EVERY == 0),
        note=f"{n} closed trades.",
    )


async def performance_for_user(client, user_id: str) -> PerformanceReport:
    """Fetch a user's closed paper positions and compute the report."""
    if not client:
        return PerformanceReport(note="Supabase not configured.")

    def _sync():
        return (
            client.table("paper_positions")
            .select("strategy, realized_pnl_usd, status, exit_at")
            .eq("user_id", user_id)
            .neq("status", "open")
            .order("exit_at", desc=False)
            .execute()
        )

    try:
        res = await asyncio.to_thread(_sync)
    except Exception:  # noqa: BLE001
        return PerformanceReport(note="Could not read trade history.")
    return compute_performance(res.data or [])
