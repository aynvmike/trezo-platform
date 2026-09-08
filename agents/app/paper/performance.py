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
HISTORY_PAGE_SIZE = 500
MAX_HISTORY_ROWS = 100_000


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
    # Legacy numeric fields above describe recorded closes, not verified
    # account returns. A successful history read does not reconcile fees,
    # partial-close lineage, execution receipts, open losses or cash flows.
    metric_basis: str = "recorded_closed_position_rows"
    recorded_closed_row_count: int = 0
    fee_treatment: str = "mixed_or_unverified"
    history_read_status: str = "not_requested"
    history_complete: bool = False
    history_rows_fetched: int = 0
    account_return_pct: float | None = None
    strategy_performance_verified: bool = False
    strategy_promotion_eligible: bool = False

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
        recorded_closed_row_count=n,
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
    """Read one book's complete closed-row history, or report its failure.

    Exact counts detect truncated and changing reads; an ID tiebreaker
    keeps rows with the same exit timestamp stable across pages. Advance
    by the returned length because a server may cap pages below our size.
    Partial results must never look like a complete performance report.
    """
    if not client:
        return PerformanceReport(note="Supabase not configured.",
                                 history_read_status="not_configured")

    rows, seen = [], set()
    expected = None

    def _incomplete(note: str) -> PerformanceReport:
        return PerformanceReport(note=note, history_read_status="incomplete",
                                 history_rows_fetched=len(rows))

    while True:
        offset = len(rows)

        def _sync():
            return (
                client.table("paper_positions")
                .select("id, strategy, realized_pnl_usd, status, exit_at", count="exact")
                .eq("user_id", user_id)
                .neq("status", "open")
                .order("exit_at", desc=False)
                .order("id", desc=False)
                .range(offset, offset + HISTORY_PAGE_SIZE - 1)
                .execute()
            )

        try:
            res = await asyncio.to_thread(_sync)
        except Exception:  # noqa: BLE001
            return PerformanceReport(
                note="Could not read complete trade history.",
                history_read_status="incomplete" if rows else "failed",
                history_rows_fetched=len(rows))

        page = getattr(res, "data", None)
        count = getattr(res, "count", None)
        if (not isinstance(page, list) or not isinstance(count, int)
                or isinstance(count, bool) or count < 0):
            return _incomplete("Trade history response was incomplete or invalid.")
        if expected is None:
            expected = count
        elif count != expected:
            return _incomplete("Trade history changed during pagination; retry required.")
        if expected > MAX_HISTORY_ROWS:
            return _incomplete("Trade history exceeds this report's read limit.")
        if not page and len(rows) != expected:
            return _incomplete("Trade history ended before the reported row count.")
        for row in page:
            rid = row.get("id") if isinstance(row, dict) else None
            if not isinstance(rid, str) or not rid or rid in seen:
                return _incomplete("Trade history contains missing or repeated row IDs.")
            seen.add(rid)
            rows.append(row)
        if len(rows) > expected:
            return _incomplete("Trade history exceeded the reported row count.")
        if len(rows) == expected:
            report = compute_performance(rows)
            report.history_read_status = "complete"
            report.history_complete = True
            report.history_rows_fetched = len(rows)
            return report
