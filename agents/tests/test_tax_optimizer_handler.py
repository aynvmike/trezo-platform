"""TC-05 (audit 2026-09-01): drive the REAL TaxOptimizerAgent.on_message.

The Tax Optimizer reacts to every `execute` on the bus with a per-trade
note for the tax ledger. Nothing in the deploy gate executed that
handler; a change to its kind gate or its message shape would have
shipped green.

Loaded through _bootstrap (stub config, no .env, no Supabase): the
handler has no seams at all -- it is pure -- so nothing is patched.
The employer-match math the tick uses is covered as well because it is
pure and the web app mirrors it (lib/tax-strategy.ts).

Run: python -m tests.run_all   (from agents/)
 or: python -m tests.test_tax_optimizer_handler
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _bootstrap import load_module, run_tests, stub_config  # noqa: E402

stub_config()
base = load_module("app.agents.base")
tax = load_module("app.agents.tax_optimizer")

AgentMessage = base.AgentMessage


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _execute(**over):
    p = {"ticker": "AMZN", "user_id": "75k-book-user-id", "venue": "paper",
         "quantity": 3, "fill_price": 210.5, "lane": "stock"}
    p.update(over)
    return AgentMessage(agent="trade_execution", kind="execute",
                        confidence=0.7, payload=p)


# --- on_message ----------------------------------------------------------------

def test_an_execute_emits_exactly_one_info_note_for_the_ticker():
    out = _run(tax.TaxOptimizerAgent().on_message(_execute()))
    assert len(out) == 1, out
    m = out[0]
    assert isinstance(m, AgentMessage)
    assert m.kind == "info"
    assert m.agent == "tax_optimizer"
    assert m.payload["ticker"] == "AMZN"
    assert "tax ledger" in m.payload["note"]
    assert "when the position closes" in m.payload["note"]


def test_every_other_kind_is_ignored():
    agent = tax.TaxOptimizerAgent()
    for kind in ("signal", "approve", "veto", "close", "info", "error",
                 "scope", "event"):
        out = _run(agent.on_message(AgentMessage(
            agent="x", kind=kind, payload={"ticker": "AMZN"})))
        assert out == [], kind


def test_a_tickerless_execute_still_answers_with_a_placeholder():
    out = _run(tax.TaxOptimizerAgent().on_message(_execute(ticker=None)))
    assert len(out) == 1 and out[0].payload["ticker"] is None
    m = _execute()
    del m.payload["ticker"]
    out = _run(tax.TaxOptimizerAgent().on_message(m))
    assert len(out) == 1 and out[0].payload["ticker"] == "?"


def test_the_note_never_carries_book_or_fill_details():
    """The note is a ledger acknowledgement, not a copy of the fill: a
    downstream reader (activity log, dashboard feed) must not learn the
    book id or price from it."""
    out = _run(tax.TaxOptimizerAgent().on_message(_execute()))
    p = out[0].payload
    assert set(p) == {"ticker", "note"}, p


def test_the_handler_is_stateless_across_many_fills():
    agent = tax.TaxOptimizerAgent()
    seen = [_run(agent.on_message(_execute(ticker=t)))[0].payload["ticker"]
            for t in ("KO", "GDX", "XRPUSD", "AMZN")]
    assert seen == ["KO", "GDX", "XRPUSD", "AMZN"]


# --- the employer-match math the tick relies on (pure) -----------------------

def test_match_left_on_table_matches_the_web_apps_formula():
    # $100k salary, contributing 3%, employer matches 50% up to 6%:
    # captured = 100k * 3% * 0.5 = 1,500; full = 100k * 6% * 0.5 = 3,000
    match, left = tax._match_left_on_table(100_000, 3, 50, 6)
    assert round(match, 2) == 1_500.00
    assert round(left, 2) == 1_500.00
    # contributing at or above the cap leaves nothing on the table
    match, left = tax._match_left_on_table(100_000, 6, 50, 6)
    assert round(match, 2) == 3_000.00 and left == 0.0
    match, left = tax._match_left_on_table(100_000, 10, 50, 6)
    assert round(match, 2) == 3_000.00 and left == 0.0


def test_match_math_clamps_junk_inputs_instead_of_raising():
    assert tax._match_left_on_table(None, None, None, None) == (0.0, 0.0)
    assert tax._match_left_on_table(-5, -1, -3, -2) == (0.0, 0.0)
    match, left = tax._match_left_on_table(50_000, 250, 100, 300)
    assert round(match, 2) == 50_000.00 and left == 0.0   # pct capped at 100


def test_setaside_rate_is_the_documented_conservative_default():
    """Not a knob test -- the agent's note quotes this rate to the user."""
    assert tax.DEFAULT_SETASIDE_RATE == 0.22


if __name__ == "__main__":
    sys.exit(run_tests(dict(globals())))
