"""APScheduler wiring for agent tick loops.

Each agent declares its own cadence via its `tick_interval_seconds` attr.
When the scheduler fires, it calls `agent.tick()` if the agent is enabled,
collects emitted messages, publishes them onto the bus, and updates the
registry's bookkeeping.
"""

from __future__ import annotations

import asyncio

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
import structlog

from .bus import bus
from .persistence import persist_message
from .registry import registry, AgentState


log = structlog.get_logger("trezo.scheduler")
_scheduler: AsyncIOScheduler | None = None


def _tick_timeout_for(impl) -> float:
    """Hard ceiling for one tick. 2026-06-11 PM: GET /agents showed a
    wave of agents (pattern_detection, exit advisors, adaptive_scope,
    forex) whose ticks HUNG mid-day and never returned. With
    max_instances=1 a hung tick silences that agent for the rest of the
    process lifetime -- no error, no log, nothing. Bound every tick so
    a hang becomes a visible last_error and the next fire can run."""
    # 2026-08-27: an agent may declare its own ceiling. The 900s cap
    # silently CANCELLED options_scanner's every tick once its wheel
    # pass outgrew 15 minutes (85-name market-wide universe x 3 books)
    # -- messages discarded, error only on stdout, agent "silent" for
    # 9+ hours across four boots. An explicit tick_timeout_seconds
    # beats the formula; max_instances=1 + coalesce keep a long tick
    # from ever overlapping the next fire.
    own = getattr(impl, "tick_timeout_seconds", None)
    if own:
        try:
            return float(max(120.0, float(own)))
        except (TypeError, ValueError):
            pass
    interval = getattr(impl, "tick_interval_seconds", 60) or 60
    return float(min(max(2 * interval, 120), 900))


async def _tick_agent(state: AgentState) -> None:
    if not state.enabled or not state.impl:
        return
    timeout_s = _tick_timeout_for(state.impl)
    try:
        messages = await asyncio.wait_for(state.impl.tick(), timeout=timeout_s)
    except asyncio.TimeoutError:
        state.last_error = f"tick timed out after {timeout_s:.0f}s (hung await or blocked I/O)"
        log.error("agent.tick.timeout", agent=state.name, timeout_s=timeout_s)
        # 2026-08-27: say it ON THE BUS, not just stdout. A cancelled
        # tick used to discard its messages and leave nothing anywhere
        # a human or the watchdog reads -- the scanner was cancelled
        # every tick for 9 hours and the only trace was a stdout line
        # nobody can reach remotely. Never again silently.
        try:
            from app.agents.base import AgentMessage as _AM
            await bus.publish(_AM(
                agent=state.name, kind="error",
                payload={"event": "tick_cancelled_timeout",
                         "timeout_s": int(timeout_s),
                         "note": (f"tick exceeded {int(timeout_s)}s and "
                                  f"was cancelled - all its messages "
                                  f"were lost; raise "
                                  f"tick_timeout_seconds or shrink the "
                                  f"tick")}))
        except Exception:  # noqa: BLE001
            pass
        return
    except Exception as e:  # noqa: BLE001
        state.last_error = str(e)
        log.error("agent.tick.failed", agent=state.name, error=str(e))
        return

    state.mark_ticked()
    state.last_error = None

    for m in messages or []:
        state.message_count += 1
        await bus.publish(m)
        # Patched 2026-06-05: duplicate persist removed. bus.publish()
        # already triggers the _persist subscriber registered in
        # bootstrap.py, which calls persist_message exactly once. The
        # scheduler-side direct call was writing every scheduled
        # message TWICE -- doubling Supabase load for no reason.


def start_scheduler() -> None:
    """Register all known agents on their interval triggers and start ticking."""
    global _scheduler
    if _scheduler is not None:
        return

    # 2026-06-11 PM: job_defaults added. APScheduler's default
    # misfire_grace_time is 1 SECOND -- any fire that came due while the
    # event loop was blocked (e.g. the old inline yfinance calls) was
    # silently SKIPPED ("Run time ... was missed"). During market hours
    # the loop was busy enough that 11 agents (crypto_scanner included,
    # at a 180s interval) never got a single tick in 6+ hours.
    # grace=None means "run it whenever the loop frees up, however
    # late"; coalesce collapses a backlog into one run.
    _scheduler = AsyncIOScheduler(job_defaults={
        "misfire_grace_time": None,
        "coalesce": True,
        "max_instances": 1,
    })

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
