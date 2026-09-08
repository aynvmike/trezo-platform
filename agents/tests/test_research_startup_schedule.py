"""The real scheduler starts research promptly without a second tick loop."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import load_module, run_tests, stub_config

stub_config()
scheduler = load_module("app.runtime.scheduler")
discovery = load_module("app.agents.strategy_discovery")
refresh = load_module("app.runtime.refresh_tokens")

_NOW = datetime(2026, 9, 8, 20, 0, tzinfo=timezone.utc)
_UNSET = object()


class _Clock:
    @staticmethod
    def now(tz):
        assert tz is timezone.utc
        return _NOW


class _Scheduler:
    def __init__(self, **kwargs):
        self.options = kwargs
        self.jobs = []
        self.starts = 0

    def add_job(self, func, **kwargs):
        self.jobs.append({"func": func, **kwargs})

    def start(self):
        self.starts += 1


def _state(name, interval=60, delay=_UNSET):
    impl = SimpleNamespace(tick_interval_seconds=interval)
    if delay is not _UNSET:
        impl.tick_initial_delay_seconds = delay
    return scheduler.AgentState(name=name, description="test", impl=impl)


@contextmanager
def _wired(states):
    saved = {name: getattr(scheduler, name)
             for name in ("AsyncIOScheduler", "registry", "_scheduler", "datetime")}
    prior_refresh = refresh.schedule_refresh_token_job
    try:
        scheduler.AsyncIOScheduler = _Scheduler
        scheduler.registry = SimpleNamespace(all=lambda: states)
        scheduler._scheduler = None
        scheduler.datetime = _Clock
        # Isolate token polling: this suite tests agent scheduling only.
        refresh.schedule_refresh_token_job = lambda _: None
        scheduler.start_scheduler()
        yield scheduler._scheduler
    finally:
        for name, value in saved.items():
            setattr(scheduler, name, value)
        refresh.schedule_refresh_token_job = prior_refresh


def test_discovery_has_one_early_hourly_job_and_other_agents_keep_their_cadence():
    research = scheduler.AgentState(name="strategy_discovery", description="test",
                                    impl=discovery.StrategyDiscoveryAgent())
    regular = _state("regular", interval=180)
    event_only = _state("event_only", interval=0, delay=0)
    with _wired([research, regular, event_only]) as wired:
        jobs = {job["id"]: job for job in wired.jobs}
        assert len(wired.jobs) == 2, wired.jobs
        assert set(jobs) == {"tick:strategy_discovery", "tick:regular"}
        job = jobs["tick:strategy_discovery"]
        assert job["func"] is scheduler._tick_agent
        assert job["args"] == [research]
        assert job["next_run_time"] == _NOW + timedelta(seconds=30)
        assert job["next_run_time"].utcoffset() == timedelta(0)
        assert job["trigger"].interval.total_seconds() == 3600
        following = job["trigger"].get_next_fire_time(
            job["next_run_time"], job["next_run_time"])
        assert following == job["next_run_time"] + timedelta(hours=1)
        assert job["max_instances"] == 1 and job["coalesce"] is True
        assert job["replace_existing"] is True
        assert "next_run_time" not in jobs["tick:regular"]
        assert jobs["tick:regular"]["trigger"].interval.total_seconds() == 180
        assert wired.options["job_defaults"] == {
            "misfire_grace_time": None, "coalesce": True, "max_instances": 1}
        scheduler.start_scheduler()
        assert wired.starts == 1 and len(wired.jobs) == 2


def test_invalid_initial_delays_do_not_prevent_other_agents_from_scheduling():
    invalid = [True, "30", -1, 61, float("nan"), float("inf"), object(), 10 ** 400]
    states = [_state(f"invalid-{i}", delay=delay) for i, delay in enumerate(invalid)]
    states.append(_state("valid-after-invalid", delay=15))
    with _wired(states) as wired:
        assert len(wired.jobs) == len(states)
        assert all("next_run_time" not in job for job in wired.jobs[:-1])
        assert wired.jobs[-1]["next_run_time"] == _NOW + timedelta(seconds=15)
        assert wired.starts == 1


def test_initial_delay_accepts_zero_and_interval_without_altering_repeat_period():
    with _wired([_state("now", delay=0), _state("normal", delay=60)]) as wired:
        assert wired.jobs[0]["next_run_time"] == _NOW
        assert wired.jobs[1]["next_run_time"] == _NOW + timedelta(seconds=60)
        assert all(job["trigger"].interval.total_seconds() == 60 for job in wired.jobs)


def test_early_job_preserves_enabled_gate_at_execution_time():
    calls = []

    async def tick():
        calls.append("tick")
        return []

    state = _state("strategy_discovery", interval=3600, delay=30)
    state.impl.tick = tick
    with _wired([state]) as wired:
        job = wired.jobs[0]
        state.enabled = False
        asyncio.run(job["func"](*job["args"]))
        assert calls == [] and state.tick_count == 0 and state.last_error is None
        state.enabled = True
        asyncio.run(job["func"](*job["args"]))
        assert calls == ["tick"] and state.tick_count == 1 and state.last_error is None


if __name__ == "__main__":
    sys.exit(run_tests(dict(globals())))
