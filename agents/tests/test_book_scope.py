"""Guard tests: a book may never be judged by another book's holdings.

The bug these exist to prevent (2026-08-17): Position Monitor read the
broker's held-symbol set ONCE, before binding each row's account, so
every book was measured against the primary's holdings. Rows the primary
did not also hold were closed as phantoms -- nine positions in the 75k
book, eight in the 25k, all still live at Alpaca, all unmanaged, and on
crypto (no native bracket) all without a stop.

These tests use a fake position fetcher, so they need no broker, no
network and no credentials.

Run: pytest agents/tests/test_book_scope.py
 or: python -m agents.tests.test_book_scope
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _bootstrap import load_module, run_tests  # noqa: E402

book_scope = load_module("app.runtime.book_scope")
from app.brokers import accounts as acct  # noqa: E402


# --- a fake three-book world ---------------------------------------------

BOOKS = {
    "book-primary": [{"symbol": "GOOG", "asset_class": "us_equity",
                      "qty": "1", "avg_entry_price": "342.40"}],
    "book-25k": [{"symbol": "GDX", "asset_class": "us_equity",
                  "qty": "3", "avg_entry_price": "89.55"},
                 {"symbol": "LINKUSD", "asset_class": "crypto",
                  "qty": "133.7", "avg_entry_price": "8.10"}],
    "book-75k": [{"symbol": "XRPUSD", "asset_class": "crypto",
                  "qty": "714.7", "avg_entry_price": "1.0014"}],
}


def _fake_accounts():
    return [
        acct.BrokerAccount(account_id="primary", label="Primary",
                           owner_id="mike", account_key="book-primary",
                           key_id="K" * 26, secret="S" * 44),
        acct.BrokerAccount(account_id="acct2", label="25k",
                           owner_id="mike", account_key="book-25k",
                           key_id="J" * 26, secret="T" * 44),
        acct.BrokerAccount(account_id="acct3", label="75k",
                           owner_id="mike", account_key="book-75k",
                           key_id="H" * 26, secret="U" * 44),
    ]


def _install_fakes():
    """Point the registry and the broker at the fake world."""
    fake = _fake_accounts()
    acct.load_accounts = lambda: list(fake)                      # type: ignore
    acct.multi_account_active = lambda: True                     # type: ignore
    acct.primary_account = lambda: fake[0]                       # type: ignore

    def _for_user(uid):
        for a in fake:
            if a.account_key == uid:
                return a
        return None
    acct.account_for_user = _for_user                            # type: ignore
    acct.should_skip_unresolved = lambda uid: _for_user(uid) is None  # type: ignore

    # Rebind the names book_scope imported at module load.
    book_scope.account_for_user = _for_user                      # type: ignore
    book_scope.multi_account_active = lambda: True               # type: ignore
    book_scope.should_skip_unresolved = (                        # type: ignore
        lambda uid: _for_user(uid) is None)
    book_scope.verify = lambda uid: (True, "ok:test")            # type: ignore

    async def _fetch():
        a = acct.current_account()
        return list(BOOKS.get(a.account_key, [])) if a else []
    book_scope.set_positions_fetcher(_fetch)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# --- the tests ------------------------------------------------------------

def test_each_book_sees_only_its_own_holdings():
    """The whole bug in one assertion."""
    _install_fakes()
    book_scope.new_cycle()
    primary = _run(book_scope.held_symbols("book-primary"))
    k25 = _run(book_scope.held_symbols("book-25k"))
    k75 = _run(book_scope.held_symbols("book-75k"))
    assert primary == {"GOOG"}
    assert k25 == {"GDX", "LINKUSD"}
    assert k75 == {"XRPUSD"}
    assert "GDX" not in primary, (
        "the 25k's GDX must never appear in the primary's holdings")


def test_a_books_position_is_not_a_phantom_just_because_another_book_lacks_it():
    """Reproduces the exact phantom-close test the monitor makes."""
    _install_fakes()
    book_scope.new_cycle()
    # GDX lives in the 25k book. The primary does not hold it.
    assert _run(book_scope.holds("book-25k", "GDX", "stock")) is True
    assert _run(book_scope.holds("book-primary", "GDX", "stock")) is False
    # And the crypto spelling problem is handled by the asset policy.
    assert _run(book_scope.holds("book-75k", "XRP", "crypto")) is True
    assert _run(book_scope.holds("book-25k", "LINK", "crypto")) is True


def test_the_cache_is_per_book_not_global():
    _install_fakes()
    book_scope.new_cycle()
    _run(book_scope.held_symbols("book-primary"))
    state = book_scope.cache_state()
    assert set(state) == {"book-primary"}, (
        "reading one book must not populate an answer for another")
    _run(book_scope.held_symbols("book-75k"))
    assert set(book_scope.cache_state()) == {"book-primary", "book-75k"}


def test_a_failed_broker_read_is_none_not_empty():
    """None means 'could not check'. Returning an empty set instead is
    what closes real positions."""
    _install_fakes()
    book_scope.new_cycle()

    async def _boom():
        raise RuntimeError("broker timeout")
    book_scope.set_positions_fetcher(_boom)
    got = _run(book_scope.held_symbols("book-75k"))
    assert got is None, "a failed read must never look like 'holds nothing'"
    assert "book-75k" not in book_scope.cache_state(), (
        "a failure must not be cached -- one blip would become 45 seconds "
        "of phantom closes")


def test_an_unresolved_book_is_refused_not_defaulted():
    _install_fakes()
    book_scope.new_cycle()
    assert _run(book_scope.held_symbols("book-that-does-not-exist")) is None


def test_binding_yields_the_right_book_and_restores_after():
    _install_fakes()
    with book_scope.bind("book-75k") as b:
        assert b is not None and b.key == "book-75k"
        assert acct.current_account().account_key == "book-75k"
    assert acct.current_account().account_key == "book-primary", (
        "the binding must not leak past its block")


def test_assert_bound_raises_for_the_wrong_book():
    _install_fakes()
    book_scope.verify = lambda uid: (                            # type: ignore
        (True, "ok") if uid == "book-75k" else (False, "bound elsewhere"))
    with book_scope.bind("book-75k"):
        book_scope.assert_bound("book-75k")                      # no raise
        raised = False
        try:
            book_scope.assert_bound("book-25k", where="test")
        except book_scope.BookScopeError:
            raised = True
        assert raised, (
            "an action for a book other than the bound one must raise, "
            "not quietly hit the default account")


def test_new_cycle_clears_every_book():
    _install_fakes()
    book_scope.new_cycle()
    _run(book_scope.held_symbols("book-25k"))
    assert book_scope.cache_state()
    book_scope.new_cycle()
    assert book_scope.cache_state() == {}


def test_monitor_reads_holdings_after_binding_not_before():
    """Source-level guard. The defect was an ORDER of operations, so this
    checks the order in the file rather than the behaviour."""
    src = (Path(__file__).resolve().parents[1] / "app" / "agents"
           / "position_monitor.py").read_text(encoding="utf-8",
                                              errors="replace")
    assert "get_open_symbols()" not in src, (
        "position_monitor must not fetch a global held-symbol set again -- "
        "ask book_scope.held_symbols(user_id) inside the row loop, which "
        "binds the book as part of answering")
    i_bind = src.find("_pm_set_account(")
    i_read = src.find("book_scope.held_symbols(")
    assert i_bind != -1 and i_read != -1
    assert i_bind < i_read, (
        "the broker read must come AFTER the per-row account binding -- "
        "the reverse is the 2026-08-17 phantom-close bug")


if __name__ == "__main__":
    sys.exit(run_tests(dict(globals())))
