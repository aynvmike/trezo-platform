"""In-process async pub/sub bus for agent messages."""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from app.patterns import Candle  # noqa: F401 — re-exported types
from app.agents.base import AgentMessage


Handler = Callable[[AgentMessage], Awaitable[None]]


class AgentBus:
    """Tiny async broker.

    Agents `subscribe(handler)` (or `subscribe(handler, kinds=["signal"])`
    to filter). They `publish(message)` to broadcast.

    There's exactly one bus per running process. Cross-process is out of
    scope until Phase 9+.
    """

    def __init__(self) -> None:
        self._subscribers: list[tuple[Handler, set[str] | None]] = []
        self._lock = asyncio.Lock()

    def subscribe(self, handler: Handler, kinds: list[str] | None = None) -> None:
        kind_set = set(kinds) if kinds else None
        self._subscribers.append((handler, kind_set))

    async def publish(self, message: AgentMessage) -> None:
        # Snapshot subscribers under lock to avoid concurrent-modification surprises
        async with self._lock:
            subs = list(self._subscribers)
        for handler, kinds in subs:
            if kinds and message.kind not in kinds:
                continue
            try:
                await handler(message)
            except Exception as e:  # noqa: BLE001
                # A single bad subscriber must not poison the bus
                # eslint-disable-next-line — just log and continue
                print(f"[bus] subscriber {handler!r} raised: {e}")


# A single process-level instance.
bus = AgentBus()
