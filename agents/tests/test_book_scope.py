"""Guard tests: a book may never be judged by another book's holdings.

The bug these exist to prevent (2026-08-17): Position Monitor read the
broker's held-symbol set ONCE, before binding each row's account, so
every book was measured against the primary's holdings. Rows the primary
did not also hold were closed as phantoms -- nine positions in the 75k
book, eight in the 25k, all still live at Alpaca, all unmanaged, and on
crypto (no native bracket) all without a stop.

These tests use a fake position fetcher, so they need no broker, no
network and no credentials.

LEAKED FAKES (audit 2026-09-01, rv:position_monitor + rv:bound-hunter):
the fake three-book registry used to be installed by plain assignment
and never restored, so every suite that ran after this one in run_all's
single process saw accounts.load_accounts / account_for_user /
multi_account_active / primary_account / should_skip_unresolved and the
book_scope names answering for books that do not exist. The fakes now
live inside `_fake_world()`, a contextmanager that puts every real
attribute back in `finally`, and the last test in the file (sorted last
by name on purpose -- run_tests runs them in name order) proves the real
attributes are back by identity.

Run: pytest agents/tests/test_book_scope.py
 or: python -m agents.tests.test_book_scope
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _bootstrap import load_module, run_tests, stub_config  # noqa: E402

stub_config()  # app.brokers.accounts reads settings at import
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


# The REAL attributes, captured at import so the last test can prove by
# identity that nothing in this file left them replaced.
_ACCT_NAMES = ("load_accounts", "multi_account_active", "primary_account",
               "account_for_user", "should_skip_unresolved")
_SCOPE_NAMES = ("account_for_user", "multi_account_active",
                "should_skip_unresolved", "verify")
_REAL_ACCT = {n: getattr(acct, n) for n in _ACCT_NAMES}
_REAL_SCOPE = {n: getattr(book_scope, n) for n in _SCOPE_NAMES}
_REAL_FETCHER = book_scope._POSITIONS_FETCHER


@contextlib.contextmanager
def _patched(mod, **attrs):
    """Swap module attributes and ALWAYS put the originals back, even
    when the attribute did not exist before (sentinel, not None: a real
    attribute whose value is None must be restored, not deleted)."""
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


@contextlib.contextmanager
def _fake_world():
    """Point the registry and the broker at the fake world FOR ONE TEST.

    Everything patched here is restored on exit: the five accounts.*
    helpers, the four names book_scope imported at module load, and the
    positions fetcher (put back to whatever it was, which also clears the
    per-book cache via set_positions_fetcher -> invalidate)."""
    fake = _fake_accounts()

    def _for_user(uid):
        for a in fake:
            if a.account_key == uid:
                return a
        return None

    async def _fetch():
        a = acct.current_account()
        return list(BOOKS.get(a.account_key, [])) if a else []

    with _patched(acct,
                  load_accounts=lambda: list(fake),
                  multi_account_active=lambda: True,
                  primary_account=lambda: fake[0],
                  account_for_user=_for_user,
                  should_skip_unresolved=lambda uid: _for_user(uid) is None), \
         _patched(book_scope,
                  account_for_user=_for_user,
                  multi_account_active=lambda: True,
                  should_skip_unresolved=lambda uid: _for_user(uid) is None,
                  verify=lambda uid: (True, "ok:test")):
        prev_fetcher = book_scope._POSITIONS_FETCHER
        book_scope.set_positions_fetcher(_fetch)
        try:
            book_scope.new_cycle()
            yield
        finally:
            book_scope.set_positions_fetcher(prev_fetcher)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# --- the tests ------------------------------------------------------------

def test_each_book_sees_only_its_own_holdings():
    """The whole bug in one assertion."""
    with _fake_world():
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
    with _fake_world():
        # GDX lives in the 25k book. The primary does not hold it.
        assert _run(book_scope.holds("book-25k", "GDX", "stock")) is True
        assert _run(book_scope.holds("book-primary", "GDX", "stock")) is False
        # And the crypto spelling problem is handled by the asset policy.
        assert _run(book_scope.holds("book-75k", "XRP", "crypto")) is True
        assert _run(book_scope.holds("book-25k", "LINK", "crypto")) is True


def test_the_cache_is_per_book_not_global():
    with _fake_world():
        _run(book_scope.held_symbols("book-primary"))
        state = book_scope.cache_state()
        assert set(state) == {"book-primary"}, (
            "reading one book must not populate an answer for another")
        _run(book_scope.held_symbols("book-75k"))
        assert set(book_scope.cache_state()) == {"book-primary", "book-75k"}


def test_a_failed_broker_read_is_none_not_empty():
    """None means 'could not check'. Returning an empty set instead is
    what closes real positions."""
    async def _boom():
        raise RuntimeError("broker timeout")

    with _fake_world():
        book_scope.set_positions_fetcher(_boom)   # _fake_world restores it
        got = _run(book_scope.held_symbols("book-75k"))
        assert got is None, "a failed read must never look like 'holds nothing'"
        assert "book-75k" not in book_scope.cache_state(), (
            "a failure must not be cached -- one blip would become 45 seconds "
            "of phantom closes")


def test_an_unresolved_book_is_refused_not_defaulted():
    with _fake_world():
        assert _run(book_scope.held_symbols("book-that-does-not-exist")) is None


def test_binding_yields_the_right_book_and_restores_after():
    with _fake_world():
        with book_scope.bind("book-75k") as b:
            assert b is not None and b.key == "book-75k"
            assert acct.current_account().account_key == "book-75k"
        assert acct.current_account().account_key == "book-primary", (
            "the binding must not leak past its block")


def test_assert_bound_raises_for_the_wrong_book():
    with _fake_world(), _patched(book_scope, verify=lambda uid: (
            (True, "ok") if uid == "book-75k" else (False, "bound elsewhere"))):
        with book_scope.bind("book-75k"):
            book_scope.assert_bound("book-75k")                  # no raise
            raised = False
            try:
                book_scope.assert_bound("book-25k", where="test")
            except book_scope.BookScopeError:
                raised = True
            assert raised, (
                "an action for a book other than the bound one must raise, "
                "not quietly hit the default account")


def test_new_cycle_clears_every_book():
    with _fake_world():
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


def test_zz_nothing_is_left_patched_after_this_suite():
    """Sorted LAST on purpose (run_tests runs tests in name order): after
    every test above has run, the real registry and book_scope names must
    be back BY IDENTITY, the fetcher must be back to what it was at
    import, and no fake book may still be resolvable. This is the proof
    that the suites after this one in run_all see the real world."""
    for n, real in _REAL_ACCT.items():
        assert getattr(acct, n) is real, f"accounts.{n} is still a fake"
    for n, real in _REAL_SCOPE.items():
        assert getattr(book_scope, n) is real, f"book_scope.{n} is still a fake"
    assert book_scope._POSITIONS_FETCHER is _REAL_FETCHER, (
        "the fake positions fetcher leaked past this suite")
    assert book_scope.cache_state() == {}, "fake-book cache left behind"
    assert acct._active.get() is None, "an account binding leaked"
    # The real registry (credential-free stub settings) knows no fake book.
    assert acct.account_for_user("book-75k") is None
    assert book_scope.resolve("book-25k") is None


if __name__ == "__main__":
    sys.exit(run_tests(dict(globals())))
