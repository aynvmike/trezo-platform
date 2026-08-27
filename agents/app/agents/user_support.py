"""User Support Agent.

Phase 5 stub. Eventually answers user questions via the Anthropic API
("why was this trade blocked?", "what does this YieldMax distribution mean?",
"how is my tax estimate calculated?"). Today it's an idle sentinel in a
registry that has grown to 30 agents (count corrected 2026-08-27; this
line said 8 for months — see ops_watchdog.EXPECTED_AGENTS for the
authoritative roster).
"""

from __future__ import annotations

from .base import Agent, AgentMessage


class UserSupportAgent(Agent):
    name = "user_support"
    tick_interval_seconds = 0  # request/response only — no scheduled tick

    async def tick(self) -> list[AgentMessage]:
        return []

    async def on_message(self, message: AgentMessage) -> list[AgentMessage]:
        # Future: respond to 'question' messages by calling the Anthropic API.
        return []
