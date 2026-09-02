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
