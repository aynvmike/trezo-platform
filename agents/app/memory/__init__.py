"""
Trezo Memory layer.

The shared, cross-agent, cross-session brain. Built on top of Mem0
(https://mem0.ai) — agents log structured decisions and outcomes here,
and query similar past situations BEFORE making new decisions.

This is the foundation of the outcome-aware learning loop:
- Risk Manager logs vetoes + reasons -> learns which signals it should
  have approved.
- Exit Advisor logs alerts + outcomes -> learns when its alerts mattered.
- Cycle Awareness logs regime calls -> learns which regimes mattered.
- Each agent queries past outcomes BEFORE deciding the next action.

Wired in 2026-06-01.
"""

from .mem0_client import (
    TrezoMemory,
    get_memory,
    AgentDecision,
    TradeOutcome,
)

__all__ = [
    "TrezoMemory",
    "get_memory",
    "AgentDecision",
    "TradeOutcome",
]
