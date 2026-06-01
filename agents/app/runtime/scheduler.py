"""APScheduler wiring for agent tick loops.

Each agent declares its own cadence via its `tick_interval_seconds` attr.
When the scheduler fires, it calls `agent.tick()` if the agent is enabled,
collects emitted messages, publishes them onto the bus, and updates the
registry's bookkeeping.
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
import structlog

from .bus import bus
from .persistence import persist_message
from .registry import registry, AgentState


log = structlog.get_logger("trezo.scheduler")
_scheduler: AsyncIOScheduler | None = None


async def _tick_agent(state: AgentState) -> None:
    if not state.enabled or not state.impl:
        return
    try:
        messages = await state.impl.tick()
    except Exception as e:  # noqa: BLE001
        state.last_error = str(e)
        log.error("agent.tick.failed", agent=state.name, error=str(e))
        return

    state.mark_ticked()
    state.last_error = None

    for m in messages or []:
        state.message_count += 1
        await bus.publish(m)
        # Persist using the agent's owning user (the agent attaches it
        # into payload as 'user_id' if relevant)
        user_id = m.payload.get("user_id") if isinstance(m.payload, dict) else None
        await persist_message(m, user_id=user_id)


def start_scheduler() -> None:
    """Register all known agents on their interval triggers and start ticking."""
    global _scheduler
    if _scheduler is not None:
        return

    _scheduler = AsyncIOScheduler()

    for state in registry.all():
        impl = state.impl
        if not impl:
            continue
        interval = getattr(impl, "tick_interval_seconds", 60)
        # 0 = event-driven only (e.g. risk_manager reacts to signals via
        # on_message). Don't schedule a tick job for those — they'd spam
        # the loop at 1-second intervals doing nothing.
        if interval <= 0:
            log.info("agent.registered", agent=state.name, interval=0, mode="event-driven")
            continue
        _scheduler.add_job(
            _tick_agent,
            trigger=IntervalTrigger(seconds=interval),
            args=[state],
            id=f"tick:{state.name}",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        log.info("agent.registered", agent=state.name, interval=interval, mode="scheduled")

    # OAuth refresh-token poller. Lives off the same APScheduler
    # instance the agents use; never raises (helper handles failure).
    try:
        from app.runtime.refresh_tokens import schedule_refresh_token_job
        schedule_refresh_token_job(_scheduler)
    except Exception as e:  # noqa: BLE001
        log.warning("refresh.poll.schedule_failed", error=str(e)[:200])

    _scheduler.start()
    log.info("scheduler.started", agents=len(registry.all()))


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is None:
        return
    _scheduler.shutdown(wait=False)
    _scheduler = None
