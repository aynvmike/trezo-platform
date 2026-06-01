"""Base class for all Trezo agents.

Each agent is a long-lived component that:
- subscribes to inputs (market data, user events, other agents)
- emits messages onto the agent bus
- logs every decision with reasoning

This is the Phase-0 skeleton; full agent logic lands in Phase 5.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class AgentMessage:
    """A single message exchanged on the agent bus."""

    agent: str
    kind: str               # e.g. "signal", "veto", "log", "alert"
    payload: dict[str, Any]
    confidence: float = 0.0  # 0..1
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class Agent(abc.ABC):
    """Abstract base agent. Concrete agents implement `tick()`."""

    name: str = "base"
    enabled: bool = True
    # 0 = never auto-tick (event-driven only). Otherwise APScheduler will
    # call tick() every N seconds while enabled.
    tick_interval_seconds: int = 60

    @abc.abstractmethod
    async def tick(self) -> list[AgentMessage]:
        """Called by the scheduler. Returns 0+ messages to broadcast."""

    async def on_message(self, message: AgentMessage) -> list[AgentMessage]:
        """Default handler — override to react to other agents."""
        return []

    # ---- evolving memory (Phase 13) -------------------------------------
    # Every agent can persist durable insight and recall it later. Memory
    # written to the 'shared' scope is readable by every other agent.

    async def remember(self, topic: str, content: str, *,
                       scope: str = "shared", category: str = "insight",
                       weight_delta: float = 1.0) -> bool:
        """Persist or reinforce a memory (see app.runtime.memory)."""
        from app.runtime.memory import remember as _remember
        return await _remember(self.name, topic, content, scope=scope,
                               category=category, weight_delta=weight_delta)

    async def recall(self, *, shared: bool = True, limit: int = 20) -> list:
        """Recall memory — the shared pool by default, or this agent's
        own private memory when shared=False."""
        from app.runtime.memory import recall as _recall
        if shared:
            return await _recall(scope="shared", limit=limit)
        return await _recall(agent=self.name, scope=self.name, limit=limit)
