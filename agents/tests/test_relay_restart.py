"""The relay's self-restart must never run inside its own process tree.

The 8/20 deploy proved why: the drain's inline `nssm restart` was
spawned INSIDE the service it was stopping, so nssm's kill-tree took the
restarter down with everything else. The row said done, the guards were
green, and the engine sat dead for 28 minutes until a human typed the
start by hand. The fix hands the restart to a Task Scheduler one-shot,
which runs under the Task Scheduler service and outlives us. These
guards pin that, so a refactor cannot quietly put the inline call back.
"""
from __future__ import annotations

import inspect
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import load_module, run_tests  # noqa: E402

relay = load_module("app.runtime.ops_relay")


def test_the_drain_never_restarts_trezoagents_inline():
    src = inspect.getsource(relay.drain_once)
    assert not re.search(r"NSSM.*restart", src), (
        "drain_once invokes nssm directly again; that child dies "
        "between the STOP and the START")


def test_the_drain_routes_through_the_detached_restart():
    src = inspect.getsource(relay.drain_once)
    assert "_restart_detached" in src, (
        "drain_once no longer calls _restart_detached")


def test_the_detached_restart_rides_task_scheduler():
    calls = []
    real = relay._run
    relay._run = lambda cmd, timeout=900, cwd=None: calls.append(cmd) or "[exit 0]"
    try:
        relay._restart_detached()
    finally:
        relay._run = real
    flat = [" ".join(c) for c in calls]
    assert any("schtasks" in f and "/Create" in f for f in flat), (
        "no scheduled task was created; the restart would run in-tree")
    # 2026-08-27 live lesson, second edition: /Run + the /ST trigger on a
    # FIXED-NAME task double-fired (boots 82s apart), and the lingering
    # instance then made schtasks IGNORE the next deploy entirely. The
    # helper now creates a UNIQUELY NAMED one-shot with a single /ST
    # trigger and must NOT immediate-/Run it.
    assert not any("schtasks" in f and "/Run" in f for f in flat), (
        "/Run is back - that is the double-boot + stuck-instance bug")
    _creates = [f for f in flat if "/Create" in f]
    assert any("TrezoRelayRestart_" in f for f in _creates), (
        "the one-shot must be uniquely named (TrezoRelayRestart_<HHMMSS>) "
        "so a lingering instance can never swallow the next restart")
    assert any("/Delete" in f and "TrezoRelayRestart" in f for f in flat), (
        "the legacy fixed-name task must be cleaned up best-effort")
    assert not any(f.lower().startswith(relay.NSSM.lower()) for f in flat), (
        "the helper still execs nssm itself instead of via schtasks")


def test_the_scheduled_command_is_the_real_restart():
    calls = []
    real = relay._run
    relay._run = lambda cmd, timeout=900, cwd=None: calls.append(cmd) or "[exit 0]"
    try:
        relay._restart_detached()
    finally:
        relay._run = real
    create = next(c for c in calls if "/Create" in c)
    tr = create[create.index("/TR") + 1]
    assert "restart TrezoAgents" in tr and "nssm" in tr.lower(), (
        f"the task would run the wrong command: {tr!r}")


if __name__ == "__main__":
    sys.exit(run_tests(dict(globals())))
