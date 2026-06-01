"""Agent registry — owns the running agents and exposes their state."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.agents.base import Agent


@dataclass
class AgentState:
    """Runtime state for one agent."""
    name: str
    description: str
    enabled: bool = True
    last_tick_at: datetime | None = None
    tick_count: int = 0
    message_count: int = 0
    last_error: str | None = None
    role: str = "observer"  # 'observer' | 'actor'
    impl: Agent | None = field(default=None, repr=False)

    def snapshot(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "enabled": self.enabled,
            "last_tick_at": self.last_tick_at.isoformat() if self.last_tick_at else None,
            "tick_count": self.tick_count,
            "message_count": self.message_count,
            "last_error": self.last_error,
            "role": self.role,
        }

    def mark_ticked(self) -> None:
        self.last_tick_at = datetime.now(timezone.utc)
        self.tick_count += 1


class AgentRegistry:
    """In-memory map of agent name → AgentState. One per process."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentState] = {}

    def register(
        self,
        agent: Agent,
        description: str,
        role: str = "observer",
    ) -> AgentState:
        state = AgentState(
            name=agent.name,
            description=description,
            enabled=agent.enabled,
            role=role,
            impl=agent,
        )
        self._agents[agent.name] = state
        return state

    def get(self, name: str) -> AgentState | None:
        return self._agents.get(name)

    def all(self) -> list[AgentState]:
        return list(self._agents.values())

    def set_enabled(self, name: str, enabled: bool) -> AgentState | None:
        st = self._agents.get(name)
        if not st:
            return None
        st.enabled = enabled
        if st.impl:
            st.impl.enabled = enabled
        return st


registry = AgentRegistry()
