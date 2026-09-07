"""NET2-REFUSED guards -- a deliberate refusal is an outcome.

The Labor Day weekend case (2026-09-05..07): every book's crypto pocket
sat at or over cap (3/2, 6/6) and the stock pockets too (5/4, 6/5, 3/3),
so trade_execution refused every approval ON PURPOSE -- audibly, since
4ed24ad. But alarm B only counted fills and kills, so the watchdog
pinged Mike "EXECUTION STARVATION: none of them produced an outcome at
all" -- urgent, wrong, and every 30 minutes, about a lane that was
behaving exactly as configured.

The rule these tests pin: refusals count. A window whose approvals were
ALL refused on purpose reports once as a warn CAPACITY LOCK (free a
slot or raise a cap); an approve that VANISHES still raises the urgent
alarm, because that is the 8/27 outage shape and nothing may mask it.

Deliberately dependency-free (no pytest, no .env, no network) so the
deploy guard can run them in a bare checkout.
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
    return False


def _agent():
    a = wd.OpsWatchdogAgent()
    a._persist_alert = lambda **kw: asyncio.sleep(0)     # no Supabase
    real_check = a._check_flow

    async def _offline_check():
        if alerts.notify is _REAL_NOTIFY:
            with _patched(alerts, notify=_no_notify):
                return await real_check()
        return await real_check()
    a._check_flow = _offline_check
    return a


def _refuse(agent, n, event="pocket_at_capacity", ticker="ETH"):
    """Drive the REAL on_message with the executor's audible refusal
    shape: kind="info", payload.event naming the refusal (4ed24ad)."""
    for _ in range(n):
        _run(agent.on_message(_Msg(
            "info", {"event": event, "ticker": ticker, "user_id": "u1",
                     "note": "'crypto' pocket holds 3/2 of this book's "
                             "slots - new name refused"},
            agent="trade_execution")))


def _approve(agent, n, ticker="ETH"):
    for _ in range(n):
        _run(agent.on_message(_Msg("approve", {"ticker": ticker},
                                   agent="risk_manager")))


def _check(agent, minutes=25):
    agent._flow["since"] = time.time() - minutes * 60
    with _patched(wd, _us_market_open=lambda *_a, **_k: False):
        return _run(agent._check_flow())


# --- the counters ---------------------------------------------------------

def test_an_audible_refusal_is_counted_in_the_right_lane():
    a = _agent()
    _refuse(a, 2, ticker="ETH")                      # crypto by ticker
    _refuse(a, 1, event="book_at_capacity", ticker="QQQ")   # stock
    crypto = a._flow["lanes"].get("crypto") or {}
    stock = a._flow["lanes"].get("stock") or {}
    assert crypto.get("refusals") == 2, crypto
    assert stock.get("refusals") == 1, stock
    assert any("pocket_at_capacity" in k
               for k in crypto.get("refusal_reasons", {})), crypto


def test_an_ordinary_info_message_is_not_a_refusal():
    a = _agent()
    _run(a.on_message(_Msg("info", {"event": "sector_compass",
                                    "ticker": "ETH"})))
    _run(a.on_message(_Msg("info", "not-a-dict")))       # junk survives
    crypto = a._flow["lanes"].get("crypto") or {}
    assert crypto.get("refusals", 0) == 0, crypto


# --- the judge ------------------------------------------------------------

def test_a_fully_refused_window_is_a_capacity_lock_not_a_starvation():
    """The Labor Day shape: every approval answered with a deliberate
    per-book refusal. One warn, named for what it is -- and NOT the
    urgent 'nothing produced an outcome' alarm."""
    a = _agent()
    _approve(a, 6)
    _refuse(a, 14)          # per-book: refusals routinely exceed approves
    out = _check(a)
    events = [m.payload.get("event") for m in out]
    assert "capacity_lock" in events, events
    assert "execution_starvation" not in events, events
    lock = [m.payload for m in out
            if m.payload.get("event") == "capacity_lock"][0]
    assert lock["lane"] == "crypto"
    assert lock["refusals"] == 14
    assert "refused on purpose" in lock["note"]
    assert ("capacity_lock", "crypto") in a._open_alerts


def test_a_vanished_approve_still_raises_the_urgent_alarm():
    """Refusals must never mask the 8/27 shape: if even part of the
    window VANISHED, the urgent alarm fires and says how many."""
    a = _agent()
    _approve(a, 6)
    _refuse(a, 2)
    out = _check(a)
    b = [m.payload for m in out
         if m.payload.get("event") == "execution_starvation"]
    assert b, [m.payload for m in out]
    assert b[0]["refusals"] == 2
    assert b[0]["unaccounted"] == 4
    assert "4 produced NO outcome" in b[0]["note"], b[0]["note"]
    assert "2 per-book refusal(s)" in b[0]["note"], b[0]["note"]


def test_kills_keep_the_urgent_alarm_even_when_refusals_cover_the_rest():
    """A wash-trade 403 (a kill) beside capacity refusals is still an
    involuntary death: urgent, with the kill reason named."""
    a = _agent()
    _approve(a, 4)
    _refuse(a, 3)
    _run(a.on_message(_Msg(
        "error", {"event": "execute_error", "lane": "crypto",
                  "error": "HTTP 403: potential wash trade detected",
                  "ticker": "ETH"},
        agent="trade_execution")))
    out = _check(a)
    b = [m.payload for m in out
         if m.payload.get("event") == "execution_starvation"]
    assert b, [m.payload for m in out]
    assert "wash trade" in b[0]["note"], b[0]["note"]
    assert "capacity_lock" not in [m.payload.get("event") for m in out]


def test_a_fill_clears_the_capacity_lock_dedupe():
    a = _agent()
    a._open_alerts.add(("capacity_lock", "crypto"))
    a._open_alerts.add(("execution_starvation", "crypto"))
    _run(a.on_message(_Msg("execute", {"lane": "crypto", "ticker": "ETH"},
                           agent="trade_execution")))
    _check(a)
    assert ("capacity_lock", "crypto") not in a._open_alerts
    assert ("execution_starvation", "crypto") not in a._open_alerts


def test_the_lock_dedupes_while_it_persists():
    """One warn per lane while the condition holds -- not one per
    window, which is the drumbeat this fix exists to stop."""
    a = _agent()
    sent = []

    async def _recording_notify(title, body="", **kw):
        sent.append(title)
        return True
    with _patched(alerts, notify=_recording_notify):
        _approve(a, 5); _refuse(a, 9)
        _check(a)
        _approve(a, 5); _refuse(a, 9)
        _check(a)
    assert len(sent) == 1, sent


# --- bind the names -------------------------------------------------------

def test_the_refusal_spellings_match_the_executors_own():
    """The watchdog's tuple and trade_execution's emitted events must
    not drift apart, or refusals silently stop counting again."""
    import inspect
    te = load_module("app.agents.trade_execution")
    src = inspect.getsource(te)
    for ev in wd._DELIBERATE_REFUSALS:
        assert f'"event": "{ev}"' in src, (
            f"watchdog counts '{ev}' but trade_execution never emits it")


if __name__ == "__main__":
    sys.exit(run_tests(dict(vars())))
