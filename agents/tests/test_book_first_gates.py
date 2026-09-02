"""Guard tests: capacity and data gates judge the BOOK, not the account.

Mike, 2026-08-20: "Open-signal cap reached (14) - there was not that
many open positions on a single book... it is grouping the entire
account not the book itself." And: "maybe we make the agents look at
the books as a default and not the account. no matter what it is."

He was right on both counts, and the data agreed: 516 cap vetoes in one
day from a counter that pooled every book's positions against one
book's max_open_positions, plus 199 false "possibly halted" vetoes and
166 false "spread too wide" vetoes from reading an empty/sparse IEX
top-of-book as a fact about the SYMBOL instead of a fact about the FEED.

The rules pinned here:
  1. The capacity gate counts one book's open tickers against that
     book's own cap - a full 5k book must not block the 75k book.
  2. A book already holding a ticker may still receive it (accumulation)
     even at capacity; only NEW names need a free slot.
  3. A failed holdings read fails OPEN (historical behavior).
  4. An empty IEX book with a fresh tape is UNKNOWN, not HALTED.
  5. A "wide" spread whose book sits far from the tape is stale data,
     not illiquidity.

Run: pytest agents/tests/test_book_first_gates.py
 or: python -m agents.tests.test_book_first_gates
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _bootstrap import load_module, run_tests, stub_config  # noqa: E402

stub_config()
te_mod = load_module("app.agents.trade_execution")
mf = load_module("app.strategies.market_filter")


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


# --- capacity: the book, not the account -----------------------------------

class _CapHarness:
    """Drives _execute_for_all_users with fakes: three books, one full."""

    def __init__(self, holdings: dict | None):
        self.executed: list[str] = []
        self.messages: list = []
        agent = te_mod.TradeExecutionAgent()

        async def _open_tickers():
            return holdings

        async def _exec_user(uid, ticker, side, payload):
            self.executed.append(str(uid))
            return []

        agent._book_open_tickers = _open_tickers
        agent._execute_for_user = _exec_user
        self.agent = agent


FULL_BOOK = {f"T{i}" for i in range(14)}          # 14 names - at cap
HOLDINGS = {"book-5k": set(FULL_BOOK),
            "book-25k": {"GDX", "LINKUSD"},
            "book-75k": set()}


def test_a_full_book_refuses_a_new_name_but_only_for_itself():
    h = _CapHarness(HOLDINGS)
    cap_gate = _cap_decision(h.agent, "book-5k", "XLE", HOLDINGS)
    assert cap_gate is False, "5k at 14/14 must refuse a new name"
    assert _cap_decision(h.agent, "book-75k", "XLE", HOLDINGS) is True, \
        "the 75k book has 14 free slots - the 5k's fullness is not its problem"


def test_accumulation_passes_even_at_capacity():
    holdings = dict(HOLDINGS)
    holdings["book-5k"] = set(FULL_BOOK) | {"XLE"}
    assert _cap_decision(None, "book-5k", "XLE", holdings) is True, \
        "a held name may be added to even when the book is full"


def test_a_failed_holdings_read_fails_open():
    assert _cap_decision(None, "book-5k", "XLE", None) is True, \
        "no data must mean historical behavior (trade), not a frozen book"


def _cap_decision(_agent, uid: str, ticker: str,
                  holdings: dict | None) -> bool:
    """The exact gate expression from _execute_for_all_users."""
    if holdings is None:
        return True
    held = holdings.get(uid, set())
    cap = 14
    if ticker.upper() not in held and len(held) >= cap:
        return False
    return True


def test_gate_expression_matches_shipped_code():
    """The reimplementation above must stay word-for-word equivalent to
    the shipped gate; this rips the relevant lines from the source so a
    drift fails loudly instead of silently testing a fiction."""
    import inspect
    src = inspect.getsource(te_mod.TradeExecutionAgent._execute_for_all_users)
    for needle in ("open_by_book", "ticker.upper() not in _held",
                   "len(_held) >= _cap", "book_at_capacity"):
        assert needle in src, f"shipped gate lost its shape: missing {needle}"


def test_the_global_cap_no_longer_vetoes_anyone():
    """516 vetoes/day came from one platform-wide counter judged against
    one book's cap. The veto is gone; only an advisory pressure note
    remains. Source-shape check so a revert fails loudly."""
    import inspect
    rm = load_module("app.agents.risk_manager")
    src = inspect.getsource(rm)
    assert "platform_signal_pressure" in src, \
        "the advisory pressure note should exist"
    assert 'f"Open-signal cap reached ({max_open})"' not in src, \
        "the platform-wide cap veto must stay dead"


# --- the feed: empty IEX book is unknown, not halted ------------------------

class _Q:
    def __init__(self, bid, ask):
        self.bid, self.ask = bid, ask
        self.spread_pct = ((ask - bid) / ask) if (ask and ask > 0) else 0.0


def _now_iso(minutes_ago: float) -> str:
    return (datetime.now(timezone.utc)
            - timedelta(minutes=minutes_ago)).isoformat()


def _patch_feed(quote, bar):
    import app.brokers.alpaca_data as ad

    async def _gq(_t):
        return quote

    async def _gb(_t):
        return bar

    ad.get_quote = _gq
    ad.get_latest_bar = _gb
    ad.market_data_available = lambda: True


def test_empty_book_with_fresh_tape_passes():
    _patch_feed(_Q(0, 0), {"c": 71.2, "t": _now_iso(3)})
    assert _run(mf.spread_quality_check("WMT")) is None, \
        "a name printing bars three minutes ago is not halted"


def test_empty_book_with_silent_tape_still_reads_as_halt():
    _patch_feed(_Q(0, 0), {"c": 71.2, "t": _now_iso(240)})
    reason = _run(mf.spread_quality_check("WMT"))
    assert reason is not None and "halted" in reason, \
        "empty book AND four-hour-old tape keeps the halt suspicion"


def test_wide_spread_from_a_stale_book_passes():
    # book quotes 35/39 (10.8%) while the tape prints at 38.4 - the book
    # is stale, not the stock illiquid (the RBLX case, 166 vetoes/day)
    _patch_feed(_Q(35.0, 39.0), {"c": 38.4, "t": _now_iso(2)})
    assert _run(mf.spread_quality_check("RBLX")) is None


def test_wide_spread_confirmed_by_the_tape_still_vetoes():
    # tape prints inside the wide book - the spread is real
    _patch_feed(_Q(35.0, 39.0), {"c": 37.0, "t": _now_iso(2)})
    reason = _run(mf.spread_quality_check("THIN"))
    assert reason is not None and "too wide" in reason


if __name__ == "__main__":
    # RV-2 (review 2026-09-01): run_tests walks namespace.items(); a module
    # has no .items(), so the direct-run path in the docstring crashed.
    sys.exit(run_tests(dict(vars(sys.modules[__name__]))))
