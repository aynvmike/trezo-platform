"""User Support Agent.

Phase 5 stub. Eventually answers user questions via the Anthropic API
("why was this trade blocked?", "what does this YieldMax distribution mean?",
"how is my tax estimate calculated?"). Today it's an idle sentinel so the
agent registry has all 8 entries.
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
