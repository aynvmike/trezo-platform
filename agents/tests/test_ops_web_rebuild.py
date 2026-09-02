"""web_rebuild must spawn an npm the host can actually find (2026-09-02).

The first rebuild after the audit fixes died on the Windows server with
WinError 2 because the handler spawned the bare name "npm" with shell=False.
These tests drive the REAL _npm_exe / _h_web_rebuild with shutil.which and
_run stubbed and restored.
"""
from contextlib import contextmanager

from tests import _bootstrap

_bootstrap.stub_config()
relay = _bootstrap.load_module("app.runtime.ops_relay")


@contextmanager
def _patched(mod, **attrs):
    saved = {k: getattr(mod, k) for k in attrs}
    for k, v in attrs.items():
        setattr(mod, k, v)
    try:
        yield
    finally:
        for k, v in saved.items():
            setattr(mod, k, v)


class _Win:
    platform = "win32"


class _Posix:
    platform = "linux"


def test_windows_prefers_the_cmd_shim_that_which_can_see():
    seen = []

    def which(name):
        seen.append(name)
        return r"C:\Program Files\nodejs\npm.cmd" if name == "npm.cmd" else None

    with _patched(relay, sys=_Win()), _patched(relay.shutil, which=which):
        exe = relay._npm_exe()
    assert exe.endswith("npm.cmd"), exe
    assert seen[0] == "npm.cmd"


def test_windows_falls_back_to_the_cmd_name_when_nothing_is_on_path():
    with _patched(relay, sys=_Win()), _patched(relay.shutil, which=lambda n: None):
        assert relay._npm_exe() == "npm.cmd"


def test_posix_keeps_plain_npm():
    with _patched(relay, sys=_Posix()), _patched(relay.shutil, which=lambda n: "/usr/bin/npm" if n == "npm" else None):
        assert relay._npm_exe() == "/usr/bin/npm"


def test_the_rebuild_spawns_the_resolved_executable_and_restarts_only_on_exit_zero():
    calls = []

    def fake_run(cmd, timeout=900, cwd=None):
        calls.append(list(cmd))
        return "[exit 0]\nCompiled successfully" if cmd[1] == "--prefix" else "[exit 0]\nrestarted"

    with _patched(relay, _npm_exe=lambda: r"C:\nodejs\npm.cmd", _run=fake_run, _tell=lambda *a, **k: None):
        out = relay._h_web_rebuild({})
    assert calls[0][0].endswith("npm.cmd"), calls[0]
    assert calls[0][1:3] == ["--prefix", str(relay.REPO / "web")]
    assert any("restart" in c and "TrezoWeb" in c for c in calls[1:]), calls
    assert "NOT restarted" not in out


def test_a_failed_build_never_restarts_the_site():
    calls = []
    told = []

    def fake_run(cmd, timeout=900, cwd=None):
        calls.append(list(cmd))
        return "[exit 1]\nType error"

    with _patched(relay, _npm_exe=lambda: "npm.cmd", _run=fake_run, _tell=lambda msg, **k: told.append(msg)):
        out = relay._h_web_rebuild({})
    assert len(calls) == 1 and "NOT restarted" in out and told


@contextmanager
def _patched_dict(d, **kv):
    saved = {k: d.get(k) for k in kv}
    d.update(kv)
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                d.pop(k, None)
            else:
                d[k] = v


# ---- detached completion (2026-09-02: the tick-cancelled rebuild) -------
import asyncio as _aio
from datetime import datetime as _dt, timedelta as _td, timezone as _tz


class _FakeTable:
    def __init__(self, store, name):
        self.store, self.name, self._f, self._upd = store, name, {}, None
    def select(self, *_a, **_k): return self
    def update(self, payload): self._upd = payload; return self
    def eq(self, k, v): self._f[k] = v; return self
    def order(self, *_a, **_k): return self
    def limit(self, *_a, **_k): return self
    def execute(self):
        rows = self.store.setdefault(self.name, [])
        if self._upd is not None:
            for r in rows:
                if all(r.get(k) == v for k, v in self._f.items()):
                    r.update(self._upd)
            return type("R", (), {"data": []})()
        return type("R", (), {"data": [r for r in rows if all(r.get(k) == v for k, v in self._f.items())]})()


class _FakeClient:
    def __init__(self, store): self.store = store
    def table(self, name): return _FakeTable(self.store, name)


def _run_loop(coro):
    loop = _aio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_a_web_rebuild_is_handed_to_a_detached_task_and_still_lands_done():
    store = {"ops_tasks": [{"id": "j1", "kind": "web_rebuild", "status": "queued", "args": {}, "attempts": 0}]}
    seen = []

    def fake_rebuild(args):
        seen.append("built")
        return "[exit 0]\nCompiled successfully\n[exit 0]\nTrezoWeb restarted"

    async def scenario():
        with _patched(relay, _TICK_BUSY=False), _patched_dict(relay.HANDLERS, web_rebuild=fake_rebuild):
            first = await relay.drain_once(_FakeClient(store))
            assert first == {"kind": "web_rebuild", "status": "started"}, first
            assert store["ops_tasks"][0]["status"] == "running"
            assert relay._TICK_BUSY is True          # latch held while the task runs
            second = await relay.drain_once(_FakeClient(store))
            assert second is None                     # one job at a time
            await _aio.gather(*list(relay._DETACHED_TASKS))
            assert store["ops_tasks"][0]["status"] == "done", store
            assert "Compiled successfully" in store["ops_tasks"][0]["result"]
            assert relay._TICK_BUSY is False          # released by the task
    with _patched(relay, HANDLERS=dict(relay.HANDLERS)):
        _run_loop(scenario())
    assert seen == ["built"]


def test_a_detached_failure_is_recorded_not_lost():
    store = {"ops_tasks": [{"id": "j2", "kind": "web_rebuild", "status": "queued", "args": {}, "attempts": 2}]}

    def boom(args):
        raise RuntimeError("npm exploded")

    async def scenario():
        with _patched(relay, _TICK_BUSY=False), _patched_dict(relay.HANDLERS, web_rebuild=boom):
            await relay.drain_once(_FakeClient(store))
            await _aio.gather(*list(relay._DETACHED_TASKS))
        row = store["ops_tasks"][0]
        assert row["status"] == "failed" and "npm exploded" in row["result"], row
        assert relay._TICK_BUSY is False
    with _patched(relay, HANDLERS=dict(relay.HANDLERS)):
        _run_loop(scenario())


def test_a_stranded_running_row_is_swept_to_failed_but_a_fresh_one_is_left_alone():
    old = (_dt.now(_tz.utc) - _td(minutes=relay.STALE_RUNNING_MIN + 1)).isoformat()
    fresh = _dt.now(_tz.utc).isoformat()
    store = {"ops_tasks": [
        {"id": "s1", "kind": "web_rebuild", "status": "running", "started_at": old},
        {"id": "s2", "kind": "web_rebuild", "status": "running", "started_at": fresh},
    ]}
    n = _run_loop(relay.sweep_stranded(_FakeClient(store)))
    assert n == 1
    assert store["ops_tasks"][0]["status"] == "failed" and "STRANDED" in store["ops_tasks"][0]["result"]
    assert store["ops_tasks"][1]["status"] == "running"


def test_inline_kinds_still_release_the_latch_when_they_finish():
    store = {"ops_tasks": [{"id": "j3", "kind": "report_status", "status": "queued", "args": {}, "attempts": 0}]}

    async def scenario():
        with _patched(relay, _TICK_BUSY=False), _patched_dict(relay.HANDLERS, report_status=lambda a: "[exit 0]\nok"):
            out = await relay.drain_once(_FakeClient(store))
        assert out == {"kind": "report_status", "status": "done"}, out
        assert store["ops_tasks"][0]["status"] == "done"
        assert relay._TICK_BUSY is False
    with _patched(relay, HANDLERS=dict(relay.HANDLERS)):
        _run_loop(scenario())
