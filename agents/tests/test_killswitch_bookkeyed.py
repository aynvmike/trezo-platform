"""Book-keyed kill-switch guards (audit 2026-09-01: KS-2, KS-4, KS-11,
KS-12, BI-04/PH-6).

Every one of these drives the REAL app.paper.killswitch functions with
only the Supabase client stubbed at the seam. The rules pinned:

  - KS-11: a failed paper_accounts read is None, never {} — a dead
    database must not read as "no halts anywhere".
  - KS-4:  clearing one book's broker rejects leaves the others' alone.
  - KS-2:  a book in weekly recovery still hard-halts on a fresh trip
           (daily %, streak, rejects) — recovery is not immunity.
  - BI-04/PH-6: the per-coin halt measures ONE book's losses against
           THAT book's budget; the scanner-side by-book evaluator hands
           back a verdict per book.
  - KS-12: the user-set daily dollar brake is a per-book set, None on a
           failed read.

Deliberately dependency-free (no pytest, no .env, no network) so the
deploy gate (tests/run_all.py) can run them in a bare checkout.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _bootstrap import load_module, run_tests, stub_config  # noqa: E402

stub_config()
ks = load_module("app.paper.killswitch")


def _run(coro):
    # rv:test-contract :38 -- close the loop; a fresh loop per call that is
    # never closed leaks and emits ResourceWarnings as the suite grows.
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@contextlib.contextmanager
def _patched(mod, **attrs):
    """Swap module attributes and ALWAYS put the originals back."""
    old = {k: getattr(mod, k) for k in attrs}
    try:
        for k, v in attrs.items():
            setattr(mod, k, v)
        yield
    finally:
        for k, v in old.items():
            setattr(mod, k, v)


@contextlib.contextmanager
def _clean_counters():
    """Every test that touches the in-process reject window leaves it
    exactly as it found it — run_all shares one process across suites."""
    saved = {k: list(v) for k, v in ks._broker_reject_ts.items()}
    try:
        ks._broker_reject_ts.clear()
        yield
    finally:
        ks._broker_reject_ts.clear()
        ks._broker_reject_ts.update(saved)


# --- a recording stand-in for the supabase query-builder chain ----------

class _Query:
    def __init__(self, table: str, data: list):
        self.table_name = table
        self.calls: list[tuple] = []
        self._data = data

    def __getattr__(self, name):
        def _chain(*args, **kwargs):
            self.calls.append((name, args))
            return self
        return _chain

    def execute(self):
        return types.SimpleNamespace(data=self._data)

    def has(self, method: str, *args) -> bool:
        return (method, args) in self.calls


class _Client:
    def __init__(self, **tables):
        self._tables = tables
        self.queries: list[_Query] = []

    def table(self, name):
        q = _Query(name, list(self._tables.get(name, [])))
        self.queries.append(q)
        return q

    def for_table(self, name) -> list[_Query]:
        return [q for q in self.queries if q.table_name == name]


class _RaisingClient:
    def table(self, name):
        raise RuntimeError("supabase down")


def _acct(**over) -> dict:
    base = {
        "user_id": "U1",
        "trading_halted": False, "halt_scope": None, "halt_reason": None,
        "week_start_equity_usd": 10_000.0, "week_realized_pnl_usd": 0.0,
        "day_start_equity_usd": 10_000.0, "today_realized_pnl_usd": 0.0,
        "consecutive_losses": 0,
    }
    base.update(over)
    return base


# --- KS-11: check_states fails CLOSED with None ---------------------------

def test_check_states_is_none_on_a_raising_client():
    assert _run(ks.check_states(_RaisingClient())) is None


def test_check_states_is_none_with_no_client():
    assert _run(ks.check_states(None)) is None


def test_check_states_empty_table_is_a_real_empty_answer():
    """No books is an ANSWER ({}); only a failed read is answerless."""
    out = _run(ks.check_states(_Client(paper_accounts=[])))
    assert out == {} and out is not None


# --- KS-4: per-book reject reset -----------------------------------------

def test_per_book_reset_leaves_the_other_books_rejects():
    with _clean_counters():
        ks.record_broker_reject("A")
        ks.record_broker_reject("A")
        ks.record_broker_reject("B")
        ks.record_broker_reject(None)          # '' unattributed bucket
        assert ks.broker_reject_count("A") == 3   # 2 own + 1 unattributed
        assert ks.broker_reject_count("B") == 2
        ks.reset_broker_rejects("A")
        assert ks.broker_reject_count("A") == 1, "only the '' bucket remains"
        assert ks.broker_reject_count("B") == 2, "B's window must be untouched"
        assert "" in ks._broker_reject_ts, "unattributed bucket is never cleared per book"


def test_reset_with_no_user_still_clears_everything():
    """The admin /clear-session-halt path keeps its clear-all meaning."""
    with _clean_counters():
        ks.record_broker_reject("A")
        ks.record_broker_reject(None)
        ks.reset_broker_rejects()
        assert ks.broker_reject_count() == 0
        assert ks._broker_reject_ts == {}


# --- KS-2: recovery is not immunity from the hard stops -------------------

def test_weekly_recovery_plus_daily_trip_is_a_halt():
    v = ks.evaluate(_acct(week_realized_pnl_usd=-800.0,
                          today_realized_pnl_usd=-400.0))
    assert v.halted is True and v.scope == "day" and v.mode == "halt"


def test_weekly_recovery_plus_reject_storm_is_a_halt_for_that_book_only():
    with _clean_counters():
        for _ in range(ks.MAX_BROKER_REJECTS):
            ks.record_broker_reject("A")
        a = ks.evaluate(_acct(user_id="A", week_realized_pnl_usd=-800.0))
        b = ks.evaluate(_acct(user_id="B", week_realized_pnl_usd=-800.0))
    assert a.halted is True and a.scope == "session" and a.mode == "halt"
    assert b.halted is False and b.mode == "recovery", "B's rejects are B's"


def test_weekly_recovery_alone_is_still_recovery():
    v = ks.evaluate(_acct(week_realized_pnl_usd=-800.0))
    assert v.halted is False and v.mode == "recovery"


def test_persisted_halt_still_wins_first():
    v = ks.evaluate(_acct(trading_halted=True, halt_scope="day",
                          halt_reason="Daily loss limit",
                          week_realized_pnl_usd=-800.0))
    assert v.halted is True and v.scope == "day" and v.mode == "halt"


# --- BI-04 / PH-6: the per-coin halt is one book's losses vs its budget ---

def test_coin_loss_halt_filters_the_loss_query_by_book():
    client = _Client(
        paper_positions=[{"user_id": "U1", "realized_pnl_usd": -50.0}],
        paper_accounts=[{"user_id": "U1", "current_cash_usd": 1000.0}],
    )
    # crypto budget 900 -> per-coin slice 300 -> 10% limit = $30; -50 trips.
    with _patched(ks, _crypto_budget_for=lambda acct: 900.0):
        reason = _run(ks.coin_loss_halt(client, "xrp", "U1"))
    assert reason and "XRP" in reason and "per-coin" in reason
    pos = client.for_table("paper_positions")
    assert len(pos) == 1
    assert pos[0].has("eq", "user_id", "U1"), pos[0].calls
    assert pos[0].has("eq", "ticker", "XRP")
    assert pos[0].has("eq", "asset_type", "crypto")
    acc = client.for_table("paper_accounts")
    assert acc and acc[0].has("eq", "user_id", "U1"), "budget side must be the same book"


def test_coin_loss_halt_without_user_keeps_the_unfiltered_query():
    """The scanner (no user_id) case is the by-book evaluator's job; the
    single-verdict function keeps its old platform-wide sum so nothing
    silently changes shape for callers still passing None."""
    client = _Client(paper_positions=[], paper_accounts=[])
    assert _run(ks.coin_loss_halt(client, "XRP", None)) is None
    pos = client.for_table("paper_positions")
    assert pos and not any(c[0] == "eq" and c[1][:1] == ("user_id",)
                           for c in pos[0].calls)


def test_coin_loss_halt_clear_below_the_limit():
    client = _Client(
        paper_positions=[{"user_id": "U1", "realized_pnl_usd": -10.0}],
        paper_accounts=[{"user_id": "U1", "current_cash_usd": 1000.0}],
    )
    with _patched(ks, _crypto_budget_for=lambda acct: 900.0):
        assert _run(ks.coin_loss_halt(client, "XRP", "U1")) is None


def test_coin_loss_halt_by_book_benches_only_the_books_over():
    client = _Client(
        paper_accounts=[{"user_id": "A", "current_cash_usd": 1000.0},
                        {"user_id": "B", "current_cash_usd": 1000.0},
                        {"user_id": "C", "current_cash_usd": 1000.0}],
        paper_positions=[{"user_id": "A", "realized_pnl_usd": -20.0},
                         {"user_id": "A", "realized_pnl_usd": -30.0},
                         {"user_id": "B", "realized_pnl_usd": -5.0}],
    )
    with _patched(ks, _crypto_budget_for=lambda acct: 900.0):
        out = _run(ks.coin_loss_halt_by_book(client, "xrp"))
    assert set(out) == {"A", "B", "C"}
    assert out["A"][0] is True and "XRP" in out["A"][1]
    assert out["B"] == (False, "")
    assert out["C"] == (False, ""), "no losses today reads as clear"


def test_coin_loss_halt_by_book_uses_each_books_own_budget():
    """Same losses, different budgets: the smaller book trips, the
    larger one does not — measurement is per book on BOTH sides."""
    client = _Client(
        paper_accounts=[{"user_id": "small", "current_cash_usd": 100.0},
                        {"user_id": "big", "current_cash_usd": 10_000.0}],
        paper_positions=[{"user_id": "small", "realized_pnl_usd": -50.0},
                         {"user_id": "big", "realized_pnl_usd": -50.0}],
    )
    budgets = {"small": 900.0, "big": 9_000.0}
    with _patched(ks, _crypto_budget_for=lambda a: budgets[a["user_id"]]):
        out = _run(ks.coin_loss_halt_by_book(client, "XRP"))
    assert out["small"][0] is True
    assert out["big"][0] is False


def test_coin_loss_halt_by_book_is_empty_on_a_failed_read():
    assert _run(ks.coin_loss_halt_by_book(_RaisingClient(), "XRP")) == {}
    assert _run(ks.coin_loss_halt_by_book(None, "XRP")) == {}


# --- KS-12: daily dollar brake, per book, None on failure ----------------

def test_daily_dollar_over_returns_the_right_set():
    client = _Client(
        paper_accounts=[{"user_id": "A", "today_realized_pnl_usd": -120.0},
                        {"user_id": "B", "today_realized_pnl_usd": -120.0},
                        {"user_id": "C", "today_realized_pnl_usd": -50.0},
                        {"user_id": "D", "today_realized_pnl_usd": -100.0}],
        profiles=[{"user_id": "A", "daily_loss_limit_usd": 100},
                  {"user_id": "C", "daily_loss_limit_usd": 100},
                  {"user_id": "D", "daily_loss_limit_usd": 100},
                  {"user_id": "B", "daily_loss_limit_usd": 0}],
    )
    out = _run(ks.daily_dollar_over(client))
    assert out == {"A", "D"}, out       # B: no limit set; C: under; D: at the line


def test_daily_dollar_over_is_none_on_failure():
    assert _run(ks.daily_dollar_over(_RaisingClient())) is None
    assert _run(ks.daily_dollar_over(None)) is None


def test_daily_dollar_over_no_limits_is_an_empty_set_not_none():
    client = _Client(paper_accounts=[{"user_id": "A", "today_realized_pnl_usd": -999.0}],
                     profiles=[])
    out = _run(ks.daily_dollar_over(client))
    assert out == set() and out is not None


# --- KS-10 / G11: the single-verdict wrapper is gone ----------------------

def test_check_all_is_gone():
    assert not hasattr(ks, "check_all"), "check_all collapsed books into one verdict"


if __name__ == "__main__":
    sys.exit(run_tests(dict(globals())))
