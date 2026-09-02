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

Net 2 is PER LANE since the audit (NET2-GLOBAL / NET2-COUNT-BEFORE-KILL):
a global count let one crypto approve silence a starving stock lane, and
counting at approve time let an approve that died in trade_execution
read as "the pipeline works". Two alarms per lane now: A (signals, no
approvals) and B (approvals, no fills, every one killed -- and the alert
names the top kill reason).
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
alerts = load_module("app.runtime.alerts")
activity_log = load_module("app.agents.activity_log")
_REAL_NOTIFY = alerts.notify


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _Msg:
    def __init__(self, kind, payload=None, agent="x"):
        self.kind = kind
        self.payload = payload or {}
        self.agent = agent


@contextlib.contextmanager
def _patched(mod, **attrs):
    # rv:test-contract (2026-09-01): restore by SENTINEL, not by None-check.
    # The old `if v is not None: setattr` left a patched attribute whose
    # real value was None (e.g. a lazily-filled module cache) patched
    # forever in run_all's single process.
    missing = object()
    old = {k: getattr(mod, k, missing) for k in attrs}
    try:
        for k, v in attrs.items():
            setattr(mod, k, v)
        yield
    finally:
        for k, v in old.items():
            if v is missing:
                if hasattr(mod, k):
                    delattr(mod, k)
            else:
                setattr(mod, k, v)


async def _no_notify(title, body="", **kw):
    """Webhook seam for the flow tests: never leaves the process."""
    return False


def _agent(open_market=True):
    a = wd.OpsWatchdogAgent()
    a._persist_alert = lambda **kw: asyncio.sleep(0)     # no Supabase
    # rv:test-contract (2026-09-01): the flow tests reach the REAL
    # app.runtime.alerts.notify via _raise_flow; it only stays offline
    # because no webhook is configured in the gate shell. Export
    # TREZO_ALERT_WEBHOOK there and these tests would post. So the agent's
    # own _check_flow runs under a patched-and-restored notify -- unless a
    # test has already swapped notify itself (NET2-REV-03 records what
    # arrives), in which case its recorder is left in charge.
    real_check = a._check_flow

    async def _offline_check():
        if alerts.notify is _REAL_NOTIFY:
            with _patched(alerts, notify=_no_notify):
                return await real_check()
        return await real_check()
    a._check_flow = _offline_check
    return a


def _feed(agent, signals=0, approves=0, vetoes=0, fails=0, executes=0,
          kills=0, asset_type=None, kill_reason="insufficient buying power"):
    """Drive the REAL on_message. `asset_type` is what the producers put
    on the payload (risk_manager passes the signal's asset_type through;
    trade_execution stamps "lane"); None = an unlabelled message, which
    the sensor files under the "unknown" lane."""
    base = {"asset_type": asset_type} if asset_type else {}
    # An unlabelled message with NO ticker is the only thing that lands
    # in "unknown"; a bare ticker is classified like trade_execution does.
    tick = {"ticker": "KO"} if asset_type else {}
    for _ in range(signals):
        _run(agent.on_message(_Msg("signal", dict(base))))
    for _ in range(approves):
        _run(agent.on_message(_Msg("approve", dict(base), agent="risk_manager")))
    for _ in range(vetoes):
        _run(agent.on_message(_Msg("veto", dict(base))))
    for _ in range(fails):
        _run(agent.on_message(_Msg("error", {"event": "handler_failed", **base})))
    for _ in range(executes):
        _run(agent.on_message(_Msg(
            "execute", {"lane": asset_type or "", **tick},
            agent="trade_execution")))
    for _ in range(kills):
        _run(agent.on_message(_Msg(
            "error", {"event": "execute_error", "lane": asset_type or "",
                      "error": kill_reason, **tick},
            agent="trade_execution")))


def _lane(agent, name="unknown"):
    return agent._flow["lanes"].get(name) or wd._new_lane_counters()


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
    assert a._flow["lanes"] == {}, a._flow


def test_the_counters_count_what_they_claim_to():
    a = _agent()
    _feed(a, signals=3, approves=2, vetoes=1, fails=4, executes=5, kills=6)
    c = _lane(a)                        # unlabelled -> "unknown" lane
    assert c["signals"] == 3
    assert c["approves"] == 2
    assert c["vetoes"] == 1
    assert c["handler_fails"] == 4
    assert c["executes"] == 5
    assert c["kills"] == 6
    assert c["kill_reasons"] == {"insufficient buying power": 6}


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
    # NET2-GLOBAL: the lane lookup is new surface; junk shapes there
    # must be just as unbreakable.
    _run(a.on_message(_Msg("signal", "not-a-dict")))
    _run(a.on_message(_Msg("approve", {"asset_type": None})))
    _run(a.on_message(_Msg("approve", {"asset_type": {"weird": 1}})))
    _run(a.on_message(_Msg("execute", {"lane": 42})))
    _run(a.on_message(_Msg("error", {"event": "execute_error",
                                     "error": None, "lane": ""})))
    _run(a.on_message(_Msg("error", {"event": None, "error": "x"},
                           agent="trade_execution")))
    _run(a.on_message(_Msg(None, None)))

    class _NoAgent:
        kind = "error"
        payload = {"error": "boom"}
    _run(a.on_message(_NoAgent()))      # no .agent attribute at all
    _run(a._check_flow())               # and the judge survives the mess


# --- net 2, PER LANE (NET2-GLOBAL / NET2-COUNT-BEFORE-KILL) ---------------

def test_crypto_approves_do_not_silence_a_stock_lane_starvation():
    """THE EQUITY STARVATION, replayed: crypto (24/7) keeps approving,
    the stock lane produces signals and nothing else. The old global
    counter saw approves > 0 and stayed quiet the whole time."""
    a = _agent()
    _feed(a, signals=40, vetoes=5, asset_type="us_equity")
    _feed(a, signals=6, approves=6, executes=6, asset_type="crypto")
    _age_window(a, 30)
    with _patched(wd, _us_market_open=lambda *_a, **_k: True):
        out = _run(a._check_flow())
    events = {(m.payload["event"], m.payload["lane"]) for m in out}
    assert ("approval_starvation", "stock") in events, events
    assert not any(l == "crypto" for _e, l in events), events
    p = [m.payload for m in out if m.payload["lane"] == "stock"][0]
    assert p["signals"] == 40 and p["approves"] == 0
    assert p["unaccounted"] == 35
    assert "[stock]" in p["note"]


def test_equity_spellings_all_land_in_the_stock_lane():
    a = _agent()
    for at in ("us_equity", "stock", "etf", "STOCK", "equity"):
        _feed(a, signals=1, asset_type=at)
    assert _lane(a, "stock")["signals"] == 5, a._flow["lanes"]
    assert "us_equity" not in a._flow["lanes"]


def test_unlabelled_scanner_signals_are_laned_the_way_the_executor_lanes_them():
    """BOUND, not built: pattern_detection / stms / orb / extended and
    crypto_scanner stamp NO asset_type (read their payloads). If the
    sensor only read asset_type every real signal would sit in
    'unknown' and the per-lane split would be decoration. So a bare
    ticker is classified exactly as trade_execution classifies it
    before routing: in COIN_MAP -> crypto, else stock."""
    a = _agent()
    # the exact shapes the scanners emit (see stms_scanner / crypto_scanner)
    _run(a.on_message(_Msg("signal", {"ticker": "KO", "strategy": "stms",
                                      "direction": "bullish", "tcs": 80})))
    _run(a.on_message(_Msg("signal", {"ticker": "BTC", "strategy": "crypto_breakout",
                                      "mode": "breakout"})))
    _run(a.on_message(_Msg("signal", {"ticker": "ETH/USD"})))
    _run(a.on_message(_Msg("signal", {"ticker": "xrp"})))
    _run(a.on_message(_Msg("approve", {"ticker": "KO", "asset_type": None},
                           agent="risk_manager")))
    _run(a.on_message(_Msg("veto", {"ticker": "SOL"})))
    _run(a.on_message(_Msg("info", {"event": "ops_heartbeat"})))
    lanes = a._flow["lanes"]
    assert _lane(a, "stock")["signals"] == 1 and _lane(a, "stock")["approves"] == 1
    assert _lane(a, "crypto")["signals"] == 3 and _lane(a, "crypto")["vetoes"] == 1
    assert _lane(a, "unknown")["signals"] == 0, lanes
    # and the classifier really is the executor's set, not a hardcoded 4.
    # rv:test-contract (2026-09-01): the old guard ("XLM" in set OR len==4)
    # was true in BOTH the real and the fallback case, and every ticker
    # fed above sits in the 4-coin fallback too -- a silent fallback that
    # laned DOT (the audit's coin) as 'stock' would have passed. Compare
    # against trade_execution's own set and feed a coin only COIN_MAP has.
    te = load_module("app.agents.trade_execution")
    assert set(wd._crypto_symbols()) == set(te.CRYPTO_SYMBOLS), (
        "the watchdog's lane classifier drifted from trade_execution's "
        "CRYPTO_SYMBOLS -- COIN_MAP import fell back silently?")
    assert "DOT" in wd._crypto_symbols(), "DOT missing: fallback set in use"
    _run(a.on_message(_Msg("signal", {"ticker": "DOT"})))
    assert _lane(a, "crypto")["signals"] == 4, a._flow["lanes"]
    assert _lane(a, "stock")["signals"] == 1, "DOT was laned as stock"
    src = (Path(__file__).resolve().parents[1]
           / "app" / "agents" / "trade_execution.py").read_text(encoding="utf-8")
    assert "from app.data.candles import COIN_MAP" in src, (
        "trade_execution no longer derives CRYPTO_SYMBOLS from COIN_MAP; "
        "the watchdog's lane classifier must follow it")


def test_approves_killed_at_execution_raise_alarm_b_naming_the_reason():
    """NET2-COUNT-BEFORE-KILL: approvals were counted at approve time,
    so a lane whose every approve died in trade_execution read as
    healthy. Now: approved, zero fills, every one killed -> alarm, and
    the alert says WHY they died."""
    a = _agent()
    _feed(a, signals=20, approves=5, kills=5, asset_type="us_equity",
          kill_reason="insufficient buying power for 10 KO")
    _age_window(a, 30)
    with _patched(wd, _us_market_open=lambda *_a, **_k: True):
        out = _run(a._check_flow())
    b = [m for m in out if m.payload["event"] == "execution_starvation"]
    assert b, [m.payload for m in out]
    p = b[0].payload
    assert p["lane"] == "stock"
    assert p["approves"] == 5 and p["executes"] == 0 and p["kills"] == 5
    assert p["top_kill_reason"] == "insufficient buying power for 10 KO"
    assert "insufficient buying power for 10 KO" in p["note"]
    assert "[stock]" in p["note"]
    # approvals happened, so alarm A must NOT also fire for this lane
    assert not any(m.payload["event"] == "approval_starvation" for m in out)
    assert ("execution_starvation", "stock") in a._open_alerts


def test_alarm_b_needs_the_approve_floor_and_every_one_dead():
    """Two approves that died is not evidence; five approves with one
    fill is a working (if bruised) pipeline."""
    a = _agent()
    _feed(a, signals=20, approves=2, kills=2, asset_type="us_equity")
    _age_window(a, 30)
    with _patched(wd, _us_market_open=lambda *_a, **_k: True):
        assert _run(a._check_flow()) == []
    a = _agent()
    _feed(a, signals=20, approves=5, kills=4, executes=1, asset_type="us_equity")
    _age_window(a, 30)
    with _patched(wd, _us_market_open=lambda *_a, **_k: True):
        assert _run(a._check_flow()) == []


def test_the_legacy_eventless_execution_error_still_counts_as_a_kill():
    """trade_execution's older error shape has no "event" key. Until
    every producer stamps event="execute_error", that shape from
    trade_execution is still a killed execution, not nothing."""
    a = _agent()
    _run(a.on_message(_Msg("error", {"ticker": "KO", "asset_type": "crypto",
                                     "error": "Could not read the Alpaca account"},
                           agent="trade_execution")))
    assert _lane(a, "crypto")["kills"] == 1
    # ...but an unrelated agent's error is NOT a kill
    _run(a.on_message(_Msg("error", {"error": "watchdog import failed"},
                           agent="ops_watchdog")))
    assert _lane(a, "unknown")["kills"] == 0


def test_a_healthy_lane_with_executes_stays_quiet():
    a = _agent()
    _feed(a, signals=40, approves=5, executes=5, vetoes=35, asset_type="us_equity")
    _feed(a, signals=10, approves=3, executes=2, kills=1, asset_type="crypto")
    _age_window(a, 30)
    with _patched(wd, _us_market_open=lambda *_a, **_k: True):
        assert _run(a._check_flow()) == []
    assert not a._open_alerts


def test_crypto_is_judged_even_when_the_us_market_is_closed():
    a = _agent()
    _feed(a, signals=40, asset_type="crypto")
    _feed(a, signals=40, asset_type="us_equity")     # closed -> not judged
    _age_window(a, 30)
    with _patched(wd, _us_market_open=lambda *_a, **_k: False):
        out = _run(a._check_flow())
    assert [m.payload["lane"] for m in out] == ["crypto"], [m.payload for m in out]


def test_flow_alerts_are_deduped_per_lane_and_clear_when_the_lane_recovers():
    a = _agent()
    persisted = []

    async def _p(**kw):
        persisted.append(kw)
    a._persist_alert = _p
    for _ in range(2):                  # two bad windows, one alert
        _feed(a, signals=40, asset_type="us_equity")
        _age_window(a, 30)
        with _patched(wd, _us_market_open=lambda *_a, **_k: True):
            out = _run(a._check_flow())
        assert out and out[0].payload["lane"] == "stock"
    assert [p["target"] for p in persisted] == ["stock"]
    assert [p["kind"] for p in persisted] == ["approval_starvation"]
    # the lane recovers -> the dedupe key clears so the NEXT starvation alerts
    _feed(a, signals=40, approves=1, executes=1, asset_type="us_equity")
    _age_window(a, 30)
    with _patched(wd, _us_market_open=lambda *_a, **_k: True):
        assert _run(a._check_flow()) == []
    assert ("approval_starvation", "stock") not in a._open_alerts


# --- review fixes NET2-REV-01/02/03 ------------------------------------------

def _handler_crash(agent, n, *, failing="trade_execution", trigger="approve",
                   ticker="KO", error="KeyError: 'user_id'"):
    """The EXACT shape bootstrap._announce_handler_failure publishes
    (kind=error, event=handler_failed, agent, trigger_kind, ticker)."""
    for _ in range(n):
        _run(agent.on_message(_Msg(
            "error", {"event": "handler_failed", "agent": failing,
                      "error": error, "trigger_agent": "risk_manager",
                      "trigger_kind": trigger, "ticker": ticker,
                      "occurrences": 1},
            agent=failing)))


def test_approvals_that_vanish_still_raise_alarm_b():
    """NET2-REV-01: the audit shape (kills >= approves) was blind to an
    approve with NO outcome -- trade_execution disabled, dropped, or
    answering with a kind="info" skip ('no paper accounts', 'Supabase
    unavailable'). Approvals in, zero fills out is the alarm."""
    a = _agent()
    _feed(a, signals=20, approves=5, asset_type="us_equity")   # no kills, no fills
    _age_window(a, 30)
    with _patched(wd, _us_market_open=lambda *_a, **_k: True):
        out = _run(a._check_flow())
    b = [m.payload for m in out if m.payload["event"] == "execution_starvation"]
    assert b, [m.payload for m in out]
    assert b[0]["lane"] == "stock" and b[0]["approves"] == 5
    assert b[0]["kills"] == 0 and b[0]["unaccounted"] == 5, b[0]
    assert "no" in b[0]["note"].lower() and "outcome" in b[0]["note"]
    assert ("execution_starvation", "stock") in a._open_alerts
    # mixed: three died with a reason, two vanished -- the note says both
    a = _agent()
    _feed(a, signals=20, approves=5, kills=3, asset_type="us_equity")
    _age_window(a, 30)
    with _patched(wd, _us_market_open=lambda *_a, **_k: True):
        out = _run(a._check_flow())
    b = [m.payload for m in out if m.payload["event"] == "execution_starvation"]
    assert b and b[0]["kills"] == 3 and b[0]["unaccounted"] == 2, b
    assert "insufficient buying power" in b[0]["note"]
    assert "2 produced NO outcome" in b[0]["note"], b[0]["note"]


def test_an_executor_crash_on_an_approve_is_a_killed_approve():
    """NET2-REV-01: the 8/27 shape one agent downstream. If
    trade_execution.on_message raises on every approve, bootstrap
    publishes handler_failed -- that IS the approve dying at execution,
    and the alarm must name the exception."""
    a = _agent()
    _feed(a, signals=20, approves=4, asset_type="us_equity")
    _handler_crash(a, 4)
    c = _lane(a, "stock")
    assert c["handler_fails"] == 4 and c["kills"] == 4, c
    assert c["kill_reasons"] == {"KeyError: 'user_id'": 4}, c
    # ...but risk_manager crashing on a SIGNAL is not a killed approve
    _handler_crash(a, 2, failing="risk_manager", trigger="signal",
                   error="UnboundLocalError: recovery_bump")
    c = _lane(a, "stock")
    assert c["handler_fails"] == 6 and c["kills"] == 4, c
    # and trade_execution crashing on something other than an approve is not either
    _handler_crash(a, 1, trigger="execute")
    assert _lane(a, "stock")["kills"] == 4
    _age_window(a, 30)
    with _patched(wd, _us_market_open=lambda *_a, **_k: True):
        out = _run(a._check_flow())
    b = [m.payload for m in out if m.payload["event"] == "execution_starvation"]
    assert b and b[0]["top_kill_reason"] == "KeyError: 'user_id'", b
    assert "KeyError: 'user_id'" in b[0]["note"]


def test_a_thin_window_does_not_clear_an_open_starvation_alert():
    """NET2-REV-02: only recovery (an approval / a fill) clears the
    dedupe key. A thin window is inconclusive; clearing on it re-pinged
    the webhook every other window while the lane stayed starved."""
    a = _agent()
    persisted = []

    async def _p(**kw):
        persisted.append(kw)
    a._persist_alert = _p
    _feed(a, signals=40, asset_type="us_equity")
    _age_window(a, 30)
    with _patched(wd, _us_market_open=lambda *_a, **_k: True):
        assert _run(a._check_flow())
    assert len(persisted) == 1
    _feed(a, signals=3, asset_type="us_equity")             # thin, no approvals
    _age_window(a, 30)
    with _patched(wd, _us_market_open=lambda *_a, **_k: True):
        assert _run(a._check_flow()) == []
    assert ("approval_starvation", "stock") in a._open_alerts, "thin window cleared it"
    _feed(a, signals=40, asset_type="us_equity")            # still starved
    _age_window(a, 30)
    with _patched(wd, _us_market_open=lambda *_a, **_k: True):
        assert _run(a._check_flow())
    assert len(persisted) == 1, "re-alerted without any recovery in between"
    # same for alarm B: approvals with no fills, then a window with 1 approve
    # and nothing else (below the floor), then starved again -> one persist
    a = _agent()
    persisted = []
    a._persist_alert = _p
    _feed(a, signals=20, approves=5, kills=5, asset_type="us_equity")
    _age_window(a, 30)
    with _patched(wd, _us_market_open=lambda *_a, **_k: True):
        assert _run(a._check_flow())
    _feed(a, signals=5, approves=1, kills=1, asset_type="us_equity")
    _age_window(a, 30)
    with _patched(wd, _us_market_open=lambda *_a, **_k: True):
        assert _run(a._check_flow()) == []
    assert ("execution_starvation", "stock") in a._open_alerts
    _feed(a, signals=20, approves=5, kills=5, asset_type="us_equity")
    _age_window(a, 30)
    with _patched(wd, _us_market_open=lambda *_a, **_k: True):
        assert _run(a._check_flow())
    assert [p["kind"] for p in persisted] == ["execution_starvation"], persisted


def test_the_webhook_gets_the_severity_that_was_persisted():
    """NET2-REV-03: _raise_flow pinned notify() to "urgent" whatever it
    persisted, so a fully-vetoed window (warn) pinged red. Patch the
    REAL app.runtime.alerts.notify (restored) and read what arrives."""
    alerts = load_module("app.runtime.alerts")
    got = []

    async def _notify(title, body="", **kw):
        got.append((title, kw.get("severity"), kw.get("key")))
        return False
    a = _agent()
    persisted = []

    async def _p(**kw):
        persisted.append(kw)
    a._persist_alert = _p
    _feed(a, signals=30, vetoes=30, asset_type="us_equity")     # accounted -> warn
    _feed(a, signals=30, asset_type="crypto")                    # unaccounted -> urgent
    _age_window(a, 30)
    with _patched(alerts, notify=_notify), \
            _patched(wd, _us_market_open=lambda *_a, **_k: True):
        out = _run(a._check_flow())
    assert len(out) == 2
    sev = {k: s for _t, s, k in got}
    assert sev == {"approval_starvation:stock": "warn",
                   "approval_starvation:crypto": "urgent"}, got
    assert {p["target"]: p["severity"] for p in persisted} == {
        "stock": "warn", "crypto": "urgent"}


# --- REG-05: event-driven agents are exempt from the silence check --------

def test_event_driven_agents_skip_the_silence_check_outright():
    """Read tick() as source: inside the EXPECTED_AGENTS loop the
    tick_interval_seconds <= 0 exemption must come BEFORE last_tick_at is
    consulted. It used to live only in the never-ticked branch, so one
    forced tick made risk_manager read as 'stuck' four hours later.
    (tick() itself cannot be driven here: it reaches for Supabase, the
    route audit and the relay before it gets to Check 2.)"""
    src = (Path(__file__).resolve().parents[1]
           / "app" / "agents" / "ops_watchdog.py").read_text(encoding="utf-8")
    loop = src[src.index("for name, tolerance_min in EXPECTED_AGENTS:"):]
    loop = loop[:loop.index("# --- Heartbeat info message")]
    guard = loop.index("interval_s <= 0")
    first_last_tick = loop.index('getattr(_st, "last_tick_at"')   # the READ, not the comment
    assert guard < first_last_tick, "REG-05: the exemption still sits after last_tick_at"
    tail = loop[guard:guard + 200]
    assert "continue" in tail, "the exemption must skip the agent, not just note it"
    assert loop.count("interval_s <= 0") == 1, "the old in-branch exemption should be gone"


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

@contextlib.contextmanager
def _load_router():
    """Pull the REAL _route and _announce_handler_failure out of
    bootstrap.py and run them against stubs.

    Why go to this trouble: every lesson from this week says a guard
    that only reads source proves the code EXISTS, not that it BINDS.
    Booting the real engine here is out of the question -- it would wire
    30 agents to live broker keys -- so the next best thing is to
    execute the actual function bodies, unedited, in a sandbox.

    rv:test-contract (2026-09-01): a contextmanager now. The announcer's
    late imports (`from app.agents.activity_log import record`,
    `from app.runtime.alerts import notify`) resolve against the REAL
    modules, so every gate run used to append fabricated handler_failed
    rows -- carrying the 8/27 outage's exact text -- to the live activity
    log, and would have pinged the real webhook with TREZO_ALERT_WEBHOOK
    exported. Both seams are recorders here, restored on exit; the
    recorded calls are handed back so the tests can assert the announcer
    still REACHES them (net 1 is bus + log + webhook, not bus alone).
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
    recorded = []      # activity_log.record calls
    notified = []      # alerts.notify calls

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

    def _record(event, ticker, **kw):
        recorded.append((event, ticker, kw))

    async def _notify(title, body="", **kw):
        notified.append((title, kw.get("severity"), kw.get("key")))
        return False

    ns = {
        "bus": _Bus(), "log": _Log(), "AgentMessage": _Msg,
        "_handler_fail_seen": {}, "registry": None,
        "asyncio": asyncio, "published": published,
        "recorded": recorded, "notified": notified,
    }
    for c in chunks:
        exec(compile(c, "bootstrap.py", "exec"), ns)
    with _patched(activity_log, record=_record), \
            _patched(alerts, notify=_notify):
        yield ns, published, logged, _Registry


def test_a_crashing_handler_really_does_reach_the_bus():
    with _load_router() as (ns, published, logged, _Registry):

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
    # net 1 is bus + activity log + webhook: the other two legs fired too,
    # into recorders -- never the real log file or channel.
    assert [(e, t) for e, t, _ in ns["recorded"]] == [("handler_failed", "KO")], ns["recorded"]
    assert ns["notified"] and ns["notified"][0][1] == "urgent", ns["notified"]
    assert ns["notified"][0][2] == "handler_failed:risk_manager"
    assert alerts.notify is _REAL_NOTIFY, "notify seam not restored"


def test_a_healthy_handler_publishes_no_failure_report():
    with _load_router() as (ns, published, logged, _Registry):

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
    assert ns["recorded"] == [] and ns["notified"] == []


def test_repeated_crashes_count_up_but_alert_once():
    with _load_router() as (ns, published, logged, _Registry):

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
    assert len(ns["recorded"]) == 5, "every crash belongs in the activity log"
    assert len(ns["notified"]) == 1, "the webhook must be pinged once, not per message"


if __name__ == "__main__":
    sys.exit(run_tests(dict(vars())))
