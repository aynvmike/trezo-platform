"""Guards for the two nets that would have caught the 8/27-8/31 outage.

For four trading days risk_manager.on_message raised on every signal
carrying a real direction. bootstrap._route caught it, logged to stdout,
and continued -- no bus message, no activity row, no alert. Every health
check the platform had asked "is this agent ticking?", and every one
said yes. The platform traded nothing and the log looked quiet.

Two nets now, deliberately independent, because the first one only
catches crashes and the outage class is bigger than that:

  1. A handler exception is ANNOUNCED -- bus + activity log + one
     webhook ping per agent+error.
  2. APPROVAL STARVATION -- signals going in with zero approvals coming
     out during market hours is an alarm on its own, whatever the cause:
     a crash, a gate stuck closed, a config that vetoes everything.

Net 2 is the one that matters most. It does not care WHY.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _bootstrap import load_module, run_tests, stub_config  # noqa: E402

stub_config()
wd = load_module("app.agents.ops_watchdog")


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _Msg:
    def __init__(self, kind, payload=None, agent="x"):
        self.kind = kind
        self.payload = payload or {}
        self.agent = agent


@contextlib.contextmanager
def _patched(mod, **attrs):
    old = {k: getattr(mod, k, None) for k in attrs}
    try:
        for k, v in attrs.items():
            setattr(mod, k, v)
        yield
    finally:
        for k, v in old.items():
            if v is not None:
                setattr(mod, k, v)


def _agent(open_market=True):
    a = wd.OpsWatchdogAgent()
    a._persist_alert = lambda **kw: asyncio.sleep(0)     # no Supabase
    return a


def _feed(agent, signals=0, approves=0, vetoes=0, fails=0):
    for _ in range(signals):
        _run(agent.on_message(_Msg("signal")))
    for _ in range(approves):
        _run(agent.on_message(_Msg("approve")))
    for _ in range(vetoes):
        _run(agent.on_message(_Msg("veto")))
    for _ in range(fails):
        _run(agent.on_message(_Msg("error", {"event": "handler_failed"})))


def _age_window(agent, minutes):
    agent._flow["since"] = time.time() - minutes * 60


# --- net 2: approval starvation ------------------------------------------

def test_signals_with_no_approvals_raises_the_alarm():
    """THE OUTAGE, replayed: plenty of signals, zero approvals, and the
    vetoes do not account for them."""
    a = _agent()
    _feed(a, signals=40, vetoes=5)
    _age_window(a, 30)
    with _patched(wd, _us_market_open=lambda *_a, **_k: True):
        out = _run(a._check_flow())
    assert out, "silence produced no alarm"
    p = out[0].payload
    assert p["event"] == "approval_starvation"
    assert p["approves"] == 0 and p["signals"] == 40
    assert p["unaccounted"] == 35, p
    assert "NO verdict at all" in p["note"]


def test_one_approval_is_enough_to_stay_quiet():
    """The pipeline works. Never cry wolf on a slow tape."""
    a = _agent()
    _feed(a, signals=40, approves=1, vetoes=39)
    _age_window(a, 30)
    with _patched(wd, _us_market_open=lambda *_a, **_k: True):
        assert _run(a._check_flow()) == []


def test_a_thin_window_is_never_evidence():
    """Below the signal floor we know nothing -- say nothing."""
    a = _agent()
    _feed(a, signals=int(wd.FLOW_MIN_SIGNALS) - 1)
    _age_window(a, 30)
    with _patched(wd, _us_market_open=lambda *_a, **_k: True):
        assert _run(a._check_flow()) == []


def test_a_short_window_is_never_evidence():
    a = _agent()
    _feed(a, signals=100)
    _age_window(a, 1)
    with _patched(wd, _us_market_open=lambda *_a, **_k: True):
        assert _run(a._check_flow()) == []


def test_a_closed_market_is_never_evidence():
    a = _agent()
    _feed(a, signals=100)
    _age_window(a, 30)
    with _patched(wd, _us_market_open=lambda *_a, **_k: False):
        assert _run(a._check_flow()) == []


def test_fully_vetoed_flow_is_reported_as_accounted_for():
    """Everything vetoed is a POSTURE problem, not a crash. Still worth
    an alarm -- nothing is trading -- but say which shape it is."""
    a = _agent()
    _feed(a, signals=30, vetoes=30)
    _age_window(a, 30)
    with _patched(wd, _us_market_open=lambda *_a, **_k: True):
        out = _run(a._check_flow())
    assert out and out[0].payload["unaccounted"] == 0
    assert "explain them" in out[0].payload["note"]


def test_the_window_resets_so_one_bad_window_cannot_poison_the_next():
    a = _agent()
    _feed(a, signals=40)
    _age_window(a, 30)
    with _patched(wd, _us_market_open=lambda *_a, **_k: True):
        _run(a._check_flow())
    assert a._flow["signals"] == 0 and a._flow["approves"] == 0


def test_the_counters_count_what_they_claim_to():
    a = _agent()
    _feed(a, signals=3, approves=2, vetoes=1, fails=4)
    assert a._flow["signals"] == 3
    assert a._flow["approves"] == 2
    assert a._flow["vetoes"] == 1
    assert a._flow["handler_fails"] == 4


def test_counting_never_raises_on_a_junk_message():
    """The counter runs on EVERY bus message. It must be unbreakable."""
    a = _agent()

    class _Bad:
        kind = "signal"
        agent = "x"
        @property
        def payload(self):
            raise RuntimeError("boom")
    _run(a.on_message(_Bad()))          # must not raise


# --- net 1: the router announces handler crashes -------------------------

def test_the_router_announces_a_handler_crash():
    """Read bootstrap.py: the except that swallowed the outage must now
    call the announcer, and the announcer must reach bus + log + alert."""
    src = (Path(__file__).resolve().parents[1]
           / "app" / "runtime" / "bootstrap.py").read_text()
    assert "_announce_handler_failure" in src
    assert src.count("_announce_handler_failure") >= 2, "defined but never called"
    i = src.index("agent.on_message.failed")
    tail = src[i:i + 400]
    assert "_announce_handler_failure" in tail, (
        "the on_message except still continues silently")
    body = src[src.index("async def _announce_handler_failure"):]
    for needed in ("bus.publish", "handler_failed", "activity_log", "notify"):
        assert needed in body, f"announcer never reaches {needed}"


def test_the_announcement_cannot_recurse_forever():
    """The failure report is published AS the failing agent, so _route's
    own 'skip the sender' rule stops a handler that crashes on every
    message from crashing on its own crash report."""
    src = (Path(__file__).resolve().parents[1]
           / "app" / "runtime" / "bootstrap.py").read_text()
    body = src[src.index("async def _announce_handler_failure"):]
    pub = body[body.index("bus.publish"):body.index("bus.publish") + 200]
    assert "agent=state.name" in pub, (
        "the crash report must be published as the FAILING agent or the "
        "router will hand it straight back to that same handler")


def test_the_webhook_is_pinged_once_not_per_message():
    src = (Path(__file__).resolve().parents[1]
           / "app" / "runtime" / "bootstrap.py").read_text()
    body = src[src.index("async def _announce_handler_failure"):]
    assert "_n == 1" in body, (
        "a crash repeats on every message; the alert must be deduped")




# --- net 1, EXECUTED: not "the source mentions it" but "it fires" -------

def _load_router():
    """Pull the REAL _route and _announce_handler_failure out of
    bootstrap.py and run them against stubs.

    Why go to this trouble: every lesson from this week says a guard
    that only reads source proves the code EXISTS, not that it BINDS.
    Booting the real engine here is out of the question -- it would wire
    30 agents to live broker keys -- so the next best thing is to
    execute the actual function bodies, unedited, in a sandbox.
    """
    import ast as _ast
    import textwrap
    src = (Path(__file__).resolve().parents[1]
           / "app" / "runtime" / "bootstrap.py").read_text()
    tree = _ast.parse(src)
    wanted = {"_route", "_announce_handler_failure"}
    chunks = []
    for node in _ast.walk(tree):
        if isinstance(node, _ast.AsyncFunctionDef) and node.name in wanted:
            chunks.append(textwrap.dedent(_ast.get_source_segment(src, node)))
    assert len(chunks) == 2, f"found {len(chunks)} of the 2 router functions"

    published = []
    logged = []

    class _Bus:
        async def publish(self, m):
            published.append(m)

    class _Registry:
        def __init__(self, states):
            self._s = states
        def all(self):
            return self._s

    class _Log:
        def error(self, *a, **k):
            logged.append((a, k))

    ns = {
        "bus": _Bus(), "log": _Log(), "AgentMessage": _Msg,
        "_handler_fail_seen": {}, "registry": None,
        "asyncio": asyncio, "published": published,
    }
    for c in chunks:
        exec(compile(c, "bootstrap.py", "exec"), ns)
    return ns, published, logged, _Registry


def test_a_crashing_handler_really_does_reach_the_bus():
    ns, published, logged, _Registry = _load_router()

    class _Impl:
        name = "risk_manager"
        async def on_message(self, m):
            # the exact shape of the outage
            raise UnboundLocalError(
                "cannot access local variable 'recovery_bump' where it is "
                "not associated with a value")

    class _State:
        name = "risk_manager"
        enabled = True
        impl = _Impl()
        message_count = 0

    ns["registry"] = _Registry([_State()])
    _run(ns["_route"](_Msg("signal", {"ticker": "KO"}, agent="pattern_detection")))

    assert logged, "the stdout log line was lost in the rewrite"
    assert published, "THE OUTAGE WOULD STILL BE SILENT -- nothing published"
    m = published[0]
    assert m.payload["event"] == "handler_failed", m.payload
    assert m.payload["agent"] == "risk_manager"
    assert "recovery_bump" in m.payload["error"]
    assert m.payload["trigger_kind"] == "signal"
    assert m.payload["ticker"] == "KO"
    assert m.agent == "risk_manager", "must publish AS the failing agent"


def test_a_healthy_handler_publishes_no_failure_report():
    ns, published, logged, _Registry = _load_router()

    class _Impl:
        name = "risk_manager"
        async def on_message(self, m):
            return [_Msg("approve", {"ticker": "KO"}, agent="risk_manager")]

    class _State:
        name = "risk_manager"
        enabled = True
        impl = _Impl()
        message_count = 0

    ns["registry"] = _Registry([_State()])
    _run(ns["_route"](_Msg("signal", {"ticker": "KO"}, agent="pattern_detection")))
    assert not logged
    assert len(published) == 1 and published[0].kind == "approve"


def test_repeated_crashes_count_up_but_alert_once():
    ns, published, logged, _Registry = _load_router()
    alerts = []

    class _Impl:
        name = "trade_execution"
        async def on_message(self, m):
            raise KeyError("user_id")

    class _State:
        name = "trade_execution"
        enabled = True
        impl = _Impl()
        message_count = 0

    ns["registry"] = _Registry([_State()])
    for _ in range(5):
        _run(ns["_route"](_Msg("approve", {"ticker": "KO"})))
    fails = [m for m in published if m.payload.get("event") == "handler_failed"]
    assert len(fails) == 5, "every crash belongs on the bus"
    assert [f.payload["occurrences"] for f in fails] == [1, 2, 3, 4, 5]


if __name__ == "__main__":
    sys.exit(run_tests(dict(vars())))
