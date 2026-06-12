"""Shadow-backtest queue (Task #88, Mike's 2026-06-05 rule).

When Risk Manager vetoes a signal for being out of user parameters,
we ALSO emit a shadow_trade record so the Strategy Lab can simulate
what would have happened. Over time Mike reviews: "did vetoing this
make money or lose money", which closes the learning loop without
risking capital.

Table: shadow_trade_outcomes
  - id, user_id, ticker, strategy
  - vetoed_at, veto_reason (the rule that caught it)
  - signal_payload (full original signal)
  - simulated_status: pending | done | error
  - would_have_pnl_usd: filled in by the simulator
  - holding_days, exit_reason
  - notes

This module only enqueues. The Strategy Lab background job picks them
up and runs the simulation (existing simulation_lab.py logic).
"""

from __future__ import annotations

import asyncio
from typing import Optional

from app.runtime.persistence import persist_message
from app.agents.base import AgentMessage


async def queue_shadow_trade(
    user_id: Optional[str],
    ticker: str,
    strategy: str,
    veto_reason: str,
    signal_payload: dict,
) -> None:
    """Enqueue a vetoed signal for shadow-backtest simulation.

    Best-effort - never raises into the trading path. Uses the existing
    persist_message batching so it adds zero new DB pressure.
    """
    try:
        await persist_message(
            AgentMessage(
                agent="risk_manager",
                kind="shadow_trade",
                confidence=1.0,
                payload={
                    "user_id": user_id,
                    "ticker": ticker,
                    "strategy": strategy,
                    "veto_reason": veto_reason,
                    "signal_payload": signal_payload,
                    "simulated_status": "pending",
                },
            ),
            user_id=user_id,
        )
    except Exception:  # noqa: BLE001
        pass
