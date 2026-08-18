"""Guard tests: a deploy that did nothing must never look like one that worked.

The incident (2026-08-18). The server sat on 408dd94 for two days while
eight commits piled up in GitHub and every ops_tasks row said `done`.
The cause was one line the deploy threw away:

    There is no tracking information for the current branch.

`git pull --ff-only` with no arguments needs branch tracking, and the
server had none -- it predates the GitHub repo existing. So every deploy
pulled nothing, exited non-zero, and restarted the engine anyway. The
restart is what actually hurt: twice it took the engine down (an hour on
8/17, five and a half hours on 8/18) to install code that was never
fetched.

Two failures, and these tests are one each:
  1. the pull depended on server-side config nobody set or could see
  2. self-kill jobs wrote a canned "restarting now" row BEFORE running,
     so the git output -- the one line that explained everything -- was
     discarded on every single deploy

Run: python -m agents.tests.test_ops_deploy   (or pytest)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _bootstrap import load_module, run_tests, stub_config  # noqa: E402

stub_config()
relay = load_module("app.runtime.ops_relay")

_REAL = {n: getattr(relay, n) for n in ("_run", "_head", "_tell")}


def _reset():
    for n, fn in _REAL.items():
        setattr(relay, n, fn)


def _fake_run(script):
    """script: list of (match_substring, output). Records every call."""
    calls = []

    def _r(cmd, timeout=900, cwd=None):
        joined = " ".join(str(c) for c in cmd)
        calls.append(joined)
        for needle, out in script:
            if needle in joined:
                return out
        return "[exit 0]\n"
    relay._run = _r
    return calls


def _heads(*values):
    seq = list(values)

    def _h():
        return seq.pop(0) if len(seq) > 1 else seq[0]
    relay._head = _h


def _quiet():
    said = []
    relay._tell = lambda msg, key="deploy_blocked": said.append(msg)
    return said


def test_the_pull_names_its_remote_and_branch():
    """The exact bug. Bare `git pull --ff-only` needs tracking config
    that nobody set and that is invisible from our side. Naming origin
    and main makes the deploy independent of server-side state."""
    _reset()
    calls = _fake_run([("tests.run_all", "all green across 8 suites")])
    _heads("aaaaaaaa", "bbbbbbbb")
    _quiet()
    relay._h_git_pull_restart({})
    pull = [c for c in calls if " pull " in c]
    assert pull, calls
    assert "origin main" in pull[0], (
        f"a bare pull is what silently ate eight commits: {pull[0]}")


def test_a_failed_pull_does_not_restart_the_engine():
    """This is the part that cost five and a half hours: the pull failed,
    and the engine was restarted anyway to install nothing."""
    _reset()
    calls = _fake_run([
        (" pull ", "[exit 1]\nThere is no tracking information for the "
                   "current branch."),
    ])
    _heads("aaaaaaaa")
    said = _quiet()
    out = relay._h_git_pull_restart({})
    assert relay.RESTART_SENTINEL not in out, "must NOT ask for a restart"
    assert not [c for c in calls if "restart" in c]
    assert "the pull FAILED" in out
    assert said and "aborted" in said[0].lower(), "and it has to say so"


def test_a_pull_that_changed_nothing_does_not_restart_either():
    """Restarting to install code you already have is pure downtime
    risk. Both outages so far began with an unnecessary restart."""
    _reset()
    _fake_run([])
    _heads("aaaaaaaa")           # same before and after
    _quiet()
    out = relay._h_git_pull_restart({})
    assert relay.RESTART_SENTINEL not in out
    assert "Nothing to deploy" in out


def test_a_good_pull_asks_for_the_restart_rather_than_taking_it():
    """The handler must not kill the process itself. It returns a marker
    so the drain can write the result down FIRST -- otherwise the output
    dies with us, which is exactly how the tracking error stayed hidden
    across two deploys."""
    _reset()
    calls = _fake_run([("tests.run_all", "all green across 8 suites")])
    _heads("aaaaaaaa", "bbbbbbbb")
    _quiet()
    out = relay._h_git_pull_restart({})
    assert relay.RESTART_SENTINEL in out
    assert not [c for c in calls if "nssm" in c.lower()], (
        "the handler restarted us itself - the result would be lost")


def test_red_guards_roll_the_checkout_back_and_shout():
    _reset()
    calls = _fake_run([("tests.run_all", "FAILED suites: test_book_scope")])
    _heads("aaaaaaaa", "bbbbbbbb")
    said = _quiet()
    out = relay._h_git_pull_restart({})
    assert relay.RESTART_SENTINEL not in out
    assert [c for c in calls if "reset --hard aaaaaaaa" in c], calls
    assert "ROLLED BACK" in out
    assert said, "a blocked deploy that says nothing is a deploy nobody fixes"


def test_restarting_ourselves_is_also_deferred_to_the_drain():
    _reset()
    _fake_run([])
    out = relay._h_restart_service({"service": "TrezoAgents"})
    assert out == relay.RESTART_SENTINEL


def test_restarting_another_service_still_happens_inline():
    """Only OUR OWN restart needs deferring -- it is the one that kills
    the process before it can write anything down."""
    _reset()
    calls = _fake_run([])
    out = relay._h_restart_service({"service": "TrezoWeb"})
    assert out != relay.RESTART_SENTINEL
    assert [c for c in calls if "TrezoWeb" in c]


def test_only_whitelisted_services_can_be_restarted():
    _reset()
    _fake_run([])
    try:
        relay._h_restart_service({"service": "Spooler"})
    except ValueError:
        return
    raise AssertionError("an arbitrary service name must be refused")


if __name__ == "__main__":
    sys.exit(run_tests(dict(globals())))
