"""Guard tests: every book has access to every signal by default.

The bug these exist to prevent (2026-08-20). Mike: "no matter what
account is added, removed, or newly added... they always have access to
the strategies... by default all accounts and books have access to the
platform. we can adjust in the settings."

What the data showed instead: pattern_detection stamps its signals with
the user_id of the book whose watchlist it walked (provenance). Risk
Manager passes that id through to the approve payload, and Trade
Execution treated ANY user_id as a fence - single-book execution, no
fan-out. Since only the 5k book had a watchlist, every scanner-driven
stock entry landed on the 5k alone: the 25k and 75k books took their
last one on 08-14 at 17:02 and nothing said a word.

The rule now: a user_id on an approve payload is provenance, not a
fence. Execution fans out to every book; each book's OWN settings
(book_gate.admits - lane toggles, TCS floor, auto-trade) decide per
book. A payload must say book_scoped=True to stay pinned.

These tests use fakes throughout - no broker, no network, no Supabase.

Run: pytest agents/tests/test_platform_access.py
 or: python -m agents.tests.test_platform_access
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _bootstrap import (load_module, quiet_activity_log, run_tests,  # noqa: E402
                        stub_config)

stub_config()
te_mod = load_module("app.agents.trade_execution")
AgentMessage = load_module("app.agents.base").AgentMessage  # noqa: E402
# The seams the single-book path late-imports (2026-09-02, see the pin
# tests below). Loaded here so the module attributes exist to patch.
ks = load_module("app.paper.killswitch")
persistence = load_module("app.runtime.persistence")
route_guard = load_module("app.brokers.route_guard")
settings_mod = load_module("app.runtime.settings")


# --- harness --------------------------------------------------------------

class RoutingProbe:
    """Records which path on_message took, executing neither."""

    def __init__(self, agent):
        self.fanout_calls: list[dict] = []
        self.single_calls: list[str] = []

        async def _fake_fanout(ticker, side, payload):
            self.fanout_calls.append(dict(payload))
            return []

        async def _fake_single(uid, ticker, side, payload):
            self.single_calls.append(str(uid))
            return []

        agent._execute_for_all_users = _fake_fanout
        agent._execute_for_user = _fake_single


def _approve(payload: dict) -> AgentMessage:
    return AgentMessage(agent="risk_manager", kind="approve",
                        confidence=0.55, payload=payload)


def _agent_with_probe():
    agent = te_mod.TradeExecutionAgent()
    return agent, RoutingProbe(agent)


def _run(coro):
    # GATE-07 (audit 2026-09-01): get_event_loop() is deprecated with no
    # running loop (DeprecationWarning under pytest, an error in a future
    # Python) and silently reused whatever loop an earlier suite left in
    # run_all's single process. Fresh loop per call, always closed.
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# --- the rules -------------------------------------------------------------

def test_a_stamped_signal_fans_out_to_every_book():
    """user_id = provenance. The 5k's watchlist scan must not fence the
    signal to the 5k - this is the exact shape that starved the 25k/75k
    stock lanes from 08-14 on."""
    agent, probe = _agent_with_probe()
    _run(agent.on_message(_approve({
        "ticker": "XLE", "direction": "bullish", "tcs": 61,
        "strategy": "extended", "user_id": "cf1b0460-aaaa"})))
    assert len(probe.fanout_calls) == 1, "stamped signal must fan out"
    assert probe.single_calls == [], "and must not pin to the origin book"


def test_provenance_is_kept_but_renamed_so_nothing_repins_it():
    agent, probe = _agent_with_probe()
    _run(agent.on_message(_approve({
        "ticker": "XLE", "direction": "bullish", "tcs": 61,
        "strategy": "extended", "user_id": "cf1b0460-aaaa"})))
    sent = probe.fanout_calls[0]
    assert sent.get("origin_book") == "cf1b0460-aaaa", \
        "origin book must survive as provenance for the audit trail"
    assert "user_id" not in sent, \
        "user_id must be stripped or downstream code re-pins the signal"


# --- the pin: one book, judged by its own gates -----------------------------
# Review 2026-09-02 (three skeptics, rv:leak-net): since 2b007de the
# single-book path runs _read_book_brakes BEFORE the pin, so under the
# gate's dead database (persistence._client() is None, check_states gives
# None) it fails CLOSED at trade_execution.py:205 and never reaches
# _execute_for_user. The old test asserted only "no fan-out", which the
# refusal also satisfies -- it never proved the pin, and its receipt was
# the fabricated `execute_error AGNC` row leaking into the live feed on
# every deploy. Two cases now: the healthy book, where the pin must land
# exactly one call on exactly that book; and the refusal, asserted as the
# refusal it is, with its activity-log receipt captured instead of written.

BOOK = "6ce61054-bbbb"


@contextlib.contextmanager
def _patched(mod, **attrs):
    """Swap module attributes and ALWAYS put the originals back."""
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


def _healthy(book: str) -> dict:
    """check_states' shape for one book with nothing tripped."""
    return {book: ks.KillSwitch(halted=False, scope=None, reason=None,
                                mode=None)}


@contextlib.contextmanager
def _single_book_world(states):
    """The seams the single-book path late-imports, held for one test: a
    dead database (the gate has no Supabase -- made explicit rather than
    relying on the stub key failing), a route check that passes, default
    settings, no book over its daily $ brake, and the kill-switch read
    under test. Everything is restored on exit."""
    async def _states(_client):
        return states

    async def _nobody_over(_client):
        return set()

    with _patched(persistence, _client=lambda: None), \
         _patched(route_guard, check_route=lambda uid: (True, "ok:test")), \
         _patched(settings_mod,
                  get_bot_settings=lambda uid=None: types.SimpleNamespace(
                      auto_trade_enabled=True)), \
         _patched(ks, check_states=_states, daily_dollar_over=_nobody_over):
        yield


def _pinned(book: str = BOOK) -> AgentMessage:
    return _approve({"ticker": "AGNC", "direction": "bullish", "tcs": 70,
                     "strategy": "wheel_csp", "user_id": book,
                     "book_scoped": True})


def test_book_scoped_true_still_pins_to_one_book():
    """A wheel leg or manual UI order is one book's business. The pin
    survives - it just has to be asked for by name now. With THIS book's
    kill-switch healthy: exactly one single-book call, on exactly this
    book, no fan-out, nothing written to the activity log."""
    agent, probe = _agent_with_probe()
    gate_saw: list[tuple] = []

    async def _open_gate(uid, ticker, side, payload, **kw):
        # _gate_book is the per-book gate the fan-out shares; it is proven
        # in test_fanout_bookkeyed. Here it only has to let the book
        # through -- and show that the book's kill-switch state ARRIVED.
        gate_saw.append((uid, kw.get("ks_state")))
        return te_mod._BookGate(payload=payload)
    agent._gate_book = _open_gate

    with _single_book_world(_healthy(BOOK)), quiet_activity_log() as said:
        out = _run(agent.on_message(_pinned()))
    assert probe.single_calls == [BOOK], probe.single_calls
    assert probe.fanout_calls == [], "book_scoped must not fan out"
    assert out == [], f"the probe executes nothing, yet something was emitted: {out}"
    assert len(gate_saw) == 1 and gate_saw[0][0] == BOOK, gate_saw
    assert gate_saw[0][1] is not None and gate_saw[0][1].halted is False, (
        "the book's own kill-switch state must reach the gate")
    assert [s for s in said if s[0] == "execute_error"] == [], said


def test_book_scoped_fails_closed_when_the_kill_switch_is_unreadable():
    """The refusal the old test mistook for the pin. With the kill-switch
    state unreadable the single-book path executes NOTHING, says so in
    the returned error, and writes the receipt -- captured here, so the
    deploy gate stops leaking a fabricated AGNC execute_error into the
    live feed on every restart (2026-09-02)."""
    agent, probe = _agent_with_probe()
    with _single_book_world(None), quiet_activity_log() as said:
        out = _run(agent.on_message(_pinned()))
    assert probe.fanout_calls == [], "book_scoped must not fan out"
    assert probe.single_calls == [], "fail closed means no execution at all"
    assert len(out) == 1 and out[0].kind == "error", out
    assert out[0].payload.get("event") == "execute_error", out[0].payload
    assert out[0].payload.get("user_id") == BOOK, out[0].payload
    recs = [kw for e, t, kw in said if (e, t) == ("execute_error", "AGNC")]
    assert len(recs) == 1, said
    extra = recs[0].get("extra") or {}
    assert extra.get("user_id") == BOOK and extra.get("books") == 1, extra


def test_an_unstamped_signal_fans_out_exactly_as_before():
    agent, probe = _agent_with_probe()
    _run(agent.on_message(_approve({
        "ticker": "ETHUSD", "direction": "bullish", "tcs": 52,
        "strategy": "crypto_swing"})))
    assert len(probe.fanout_calls) == 1
    assert probe.single_calls == []


def test_non_approve_messages_are_ignored():
    agent, probe = _agent_with_probe()
    _run(agent.on_message(AgentMessage(
        agent="risk_manager", kind="veto", confidence=0.2,
        payload={"ticker": "XLE", "user_id": "cf1b0460-aaaa"})))
    assert probe.fanout_calls == [] and probe.single_calls == []


if __name__ == "__main__":
    # RV-2 (review 2026-09-01): run_tests walks namespace.items(); a module
    # has no .items(), so the direct-run path in the docstring crashed.
    sys.exit(run_tests(dict(vars(sys.modules[__name__]))))
