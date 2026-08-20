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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _bootstrap import load_module, run_tests, stub_config  # noqa: E402

stub_config()
te_mod = load_module("app.agents.trade_execution")
AgentMessage = load_module("app.agents.base").AgentMessage  # noqa: E402


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
    return asyncio.get_event_loop().run_until_complete(coro)


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


def test_book_scoped_true_still_pins_to_one_book():
    """A wheel leg or manual UI order is one book's business. The pin
    survives - it just has to be asked for by name now."""
    agent, probe = _agent_with_probe()
    _run(agent.on_message(_approve({
        "ticker": "AGNC", "direction": "bullish", "tcs": 70,
        "strategy": "wheel_csp", "user_id": "6ce61054-bbbb",
        "book_scoped": True})))
    assert probe.fanout_calls == [], "book_scoped must not fan out"


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
    run_tests(sys.modules[__name__])
