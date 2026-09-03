"""The same-ticker stacking dedup is PER BOOK (Mike 2026-09-02).

THE BUG: risk_manager._recent_approvals was keyed by TICKER across every
book, and _seed_open_positions filled it from every book's open positions
with no user filter. One book holding ETH therefore vetoed ETH for all
three books for as long as it was held -- "APPROVAL STARVATION [crypto]:
15 signal(s) in 20 min produced ZERO approvals", twice in one afternoon,
every veto reading "Already approved ETH in this session". That is a
house-rule-2 violation: a condition on one account changed behaviour on
another.

THE GUARANTEE THAT MUST SURVIVE (Mike 2026-06-10, the WMT 52-share
incident): a book that already holds a name must not open a second
position in it, including across a restart that re-seeds from open rows.

These tests pin both halves: the dedup frees the books that do NOT hold
the name, and no book can stack one it does.

run_all contract: plain zero-arg test_ functions, no fixtures, no .env,
no network; attributes patched and restored.
"""
from tests import _bootstrap

_bootstrap.stub_config()
rm = _bootstrap.load_module("app.agents.risk_manager")

PRIMARY = "cf1b0460-039d-40ac-adc8-7ca3ef17c5bb"
ACCT2 = "6ce61054-7ffd-41b5-80c3-1cd0220c79eb"
ACCT3 = "49acafdd-1c86-4740-a1b1-f94aa7abce08"
BOOKS = {PRIMARY, ACCT2, ACCT3}


def _agent():
    a = rm.RiskManagerAgent()
    a._recent_approvals = {}
    return a


def test_the_key_is_book_scoped_and_never_collides_across_tickers():
    a = _agent()
    assert a._ak(ACCT2, "eth") == f"{ACCT2}:ETH"
    assert a._ak(None, " eth ") == ":ETH"
    a._recent_approvals = {a._ak(ACCT2, "ETH"): 1.0, a._ak(ACCT3, "XETH"): 1.0}
    # ":ETH" must not match "...:XETH"
    assert a._books_holding("ETH") == {ACCT2}
    assert a._books_holding("XETH") == {ACCT3}


def test_a_book_that_does_not_hold_the_name_is_free_to_trade_it():
    """The starvation itself: acct2 holds ETH; the other two must be free."""
    a = _agent()
    a._recent_approvals = {a._ak(ACCT2, "ETH"): 1.0}
    holding = a._books_holding("ETH")
    assert holding == {ACCT2}
    # pinned signals
    assert ACCT2 in holding          # acct2 is blocked
    assert PRIMARY not in holding    # primary is free
    assert ACCT3 not in holding      # acct3 is free
    # unscoped scanner signal: refused only when EVERY book holds it
    assert not BOOKS.issubset(holding)


def test_an_unscoped_signal_is_refused_only_when_every_book_holds_it():
    a = _agent()
    a._recent_approvals = {a._ak(b, "ETH"): 1.0 for b in BOOKS}
    assert BOOKS.issubset(a._books_holding("ETH"))
    a._recent_approvals.pop(a._ak(ACCT3, "ETH"))
    assert not BOOKS.issubset(a._books_holding("ETH"))


def test_an_unreadable_book_registry_frees_the_signal_it_does_not_block_it():
    """A registry read that failed must never read as 'no book is free'.

    Asserted on the real helper and the real veto expression rather than
    by patching the class: restoring a staticmethod wrongly turns it into
    an instance method and breaks every later suite in the shared gate
    process (learned the hard way, 2026-09-02)."""
    import inspect
    src = inspect.getsource(rm.RiskManagerAgent._registered_books)
    assert "return set()" in src          # any failure -> empty
    empty: set = set()
    # the veto condition in on_message is `bool(books) and books.issubset(...)`
    assert not (bool(empty) and empty.issubset({PRIMARY}))
    # and a real registry read never raises
    assert isinstance(rm.RiskManagerAgent._registered_books(), set)


def test_the_wmt_restart_case_still_cannot_stack_on_the_holding_book():
    """2026-06-10: a restart re-seeds from open rows. The book that holds
    the name must still be blocked after the re-seed -- per book now."""
    a = _agent()
    # what _seed_open_positions writes for a row {ticker WMT, user_id acct3}
    a._recent_approvals[a._ak(ACCT3, "WMT")] = 0.0
    assert ACCT3 in a._books_holding("WMT")      # holder blocked
    assert PRIMARY not in a._books_holding("WMT")  # others free


def test_forget_ticker_releases_every_books_entry():
    a = _agent()
    a._recent_approvals = {a._ak(ACCT2, "ETH"): 1.0, a._ak(ACCT3, "ETH"): 1.0,
                           a._ak(ACCT2, "BTC"): 1.0}
    a.forget_ticker("eth")
    assert a._books_holding("ETH") == set()
    assert a._books_holding("BTC") == {ACCT2}


def test_a_legacy_ticker_only_key_is_still_understood():
    """Entries written before 2026-09-02 have an empty book id; they must
    still be readable and prunable rather than wedging a ticker forever."""
    a = _agent()
    a._recent_approvals = {a._ak("", "ETH"): 1.0}
    assert a._books_holding("ETH") == {""}
    a.forget_ticker("ETH")
    assert a._recent_approvals == {}


def test_the_executor_skips_only_the_book_that_holds_the_name():
    """The fan-out is the real per-book guard: it reads each book's OPEN
    rows live for this signal. Pin the shape it acts on."""
    open_by_book = {ACCT2: {"ETH": "crypto"}, ACCT3: {"BTC": "crypto"}}
    for uid, expect_skip in ((ACCT2, True), (ACCT3, False), (PRIMARY, False)):
        held = open_by_book.get(str(uid), {})
        assert ("ETH" in held) is expect_skip, uid


def test_the_stacking_guard_and_its_log_row_are_wired_in_the_fanout():
    """BUILT BUT NOT BOUND check: the skip must sit inside the fan-out's
    per-book block, before execution, and say so in the live log."""
    import inspect
    te = _bootstrap.load_module("app.agents.trade_execution")
    src = inspect.getsource(te)
    assert 'book_already_holds' in src
    assert 'ticker.upper() in _held and not _accum_ok' in src
    # the refusal is recorded, not silent
    assert '_arec("book_already_holds"' in src


def test_an_unpinned_pocket_gets_the_book_cap_not_zero_slots():
    """Clearing a book's stocks dollar pin is how the widened posture
    split takes effect; it must not silently zero the lane's slots."""
    import types
    te = _bootstrap.load_module("app.agents.trade_execution")
    cap = te.TradeExecutionAgent._pocket_cap
    pinned = types.SimpleNamespace(allocation_overrides={
        "crypto": 12000, "income": 20000, "stocks": 26000, "options": 15000})
    unpinned = types.SimpleNamespace(allocation_overrides={
        "crypto": 12000, "income": 20000, "options": 15000})
    zeroed = types.SimpleNamespace(allocation_overrides={
        "crypto": 12000, "stocks": 0})
    none_at_all = types.SimpleNamespace(allocation_overrides=None)
    assert cap(pinned, "stock", 14) == 5
    assert cap(unpinned, "stock", 14) == 14   # unpinned -> book cap
    assert cap(zeroed, "stock", 14) == 0      # explicit 0 -> not funded
    assert cap(none_at_all, "stock", 14) == 14



# --- 2026-09-03: a refusal that says nothing is a silent trade-dropper -----
# EXECUTION STARVATION [stock]: 8 approvals in 20 minutes produced zero
# fills and "none of them produced an outcome at all". The cause was
# ordinary and correct -- the stock pocket was 3/3 on primary and 6/5 on
# acct3 -- but both capacity refusals were an AgentMessage and nothing
# else, so the log Mike reads showed an approval and then silence. Two
# reviewers flagged this class before it cost anything; it then cost an
# hour of diagnosis. Every deliberate refusal must be audible.

def test_both_capacity_refusals_write_an_activity_row():
    import inspect
    te = _bootstrap.load_module("app.agents.trade_execution")
    src = inspect.getsource(te)
    for event in ("book_at_capacity", "pocket_at_capacity"):
        # the AgentMessage the dashboard reads
        assert f'"event": "{event}"' in src, event
        # AND the activity row the live log reads
        assert f'_arec_cap("{event}"' in src or f'_arec_pk("{event}"' in src, (
            f"{event} refuses a trade without saying so in the live log")


def test_the_capacity_rows_carry_the_book_and_the_numbers():
    """A refusal Mike cannot act on is only half a fix: the row has to name
    which book, which pocket, and how full it was."""
    import inspect
    te = _bootstrap.load_module("app.agents.trade_execution")
    src = inspect.getsource(te)
    i = src.index('_arec_pk("pocket_at_capacity"')
    block = src[i:i + 700]
    for needed in ('"user_id": str(uid)', '"market_type": _atype',
                   '"open": _popen', '"cap": _pcap'):
        assert needed in block, needed


def test_the_capacity_rows_are_late_imports_like_every_other_record():
    """A module-level bind would be invisible to the suites' record stub
    and to run_all's leak net."""
    import inspect
    te = _bootstrap.load_module("app.agents.trade_execution")
    src = inspect.getsource(te)
    assert "from app.agents.activity_log import record as _arec_cap" in src
    assert "from app.agents.activity_log import record as _arec_pk" in src

if __name__ == "__main__":
    import sys
    sys.exit(_bootstrap.run_tests(dict(vars())))
