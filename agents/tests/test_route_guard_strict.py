"""Every order route requires a registered book and an explicit binding.

Drive the actual guard and ContextVar with an in-memory account registry.
No credentials, database, network, activity writer, or broker call is used.
Run directly with ``python3 -m tests.test_route_guard_strict``.
"""

from __future__ import annotations

import contextlib
from dataclasses import replace
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import load_module, run_tests, stub_config  # noqa: E402

stub_config()
accounts = load_module("app.brokers.accounts")
guard = load_module("app.brokers.route_guard")

BOOK = "sole-secondary-book"
ACCOUNT = accounts.BrokerAccount(
    account_id="acct3", label="Sole secondary", owner_id="test-owner",
    account_key=BOOK, key_id="K" * 26, secret="S" * 44,
    base_url="https://paper-api.alpaca.markets")


@contextlib.contextmanager
def _registry(*registered):
    rows = list(registered)
    with patch.object(accounts, "load_accounts", return_value=rows), \
            patch.object(guard, "load_accounts", return_value=rows), \
            accounts.use_account(None):
        yield


def _refused(uid):
    ok, note = guard.check_route(uid)
    assert ok is False, f"route accepted an invalid binding for {uid!r}"
    assert isinstance(note, str) and note, "a route refusal must explain why"
    assert ACCOUNT.key_id not in note and ACCOUNT.secret not in note, (
        "route diagnostics must not expose brokerage credentials")
    return note


def test_known_but_unbound_book_refuses_primary_fallback():
    with _registry(ACCOUNT):
        assert accounts.multi_account_active() is False
        assert accounts.current_account() is ACCOUNT, "fixture must exercise primary fallback"
        assert accounts.bound_account() is None
        _refused(BOOK)


def test_empty_or_unknown_book_is_refused_even_with_one_bound_account():
    with _registry(ACCOUNT), accounts.use_account(ACCOUNT):
        assert accounts.multi_account_active() is False
        for uid in (None, "", " ", "unknown-book"):
            _refused(uid)


def test_empty_registry_never_accepts_a_bound_or_unbound_account():
    with _registry():
        _refused(BOOK)
        with accounts.use_account(ACCOUNT):
            _refused(BOOK)


def test_same_credentials_cannot_bind_the_wrong_book_key():
    wrong_book = replace(ACCOUNT, account_key="other-book")
    with _registry(ACCOUNT), accounts.use_account(wrong_book):
        _refused(BOOK)


def test_same_book_cannot_bind_different_broker_credentials():
    wrong_credentials = replace(ACCOUNT, key_id="X" * 26)
    with _registry(ACCOUNT), accounts.use_account(wrong_credentials):
        _refused(BOOK)


def test_bound_endpoint_must_match_the_registered_paper_destination():
    for endpoint in ("https://api.alpaca.markets", "https://other.example.test"):
        wrong_destination = replace(ACCOUNT, base_url=endpoint)
        with _registry(ACCOUNT), accounts.use_account(wrong_destination):
            _refused(BOOK)


def test_registered_invalid_endpoint_is_refused_even_when_binding_matches():
    invalid = replace(ACCOUNT, base_url="https://api.alpaca.markets")
    with _registry(invalid), accounts.use_account(invalid):
        _refused(BOOK)


def test_valid_sole_secondary_account_succeeds_with_real_book_binding():
    with _registry(ACCOUNT):
        assert accounts.multi_account_active() is False
        with accounts.bind_for_user(BOOK) as bound:
            assert bound is ACCOUNT and accounts.bound_account() is ACCOUNT
            ok, note = guard.check_route(BOOK)
            assert ok is True and note == "ok:acct3", (ok, note)
        assert accounts.bound_account() is None, "the order binding must be released"


def test_legacy_version_suffix_and_trailing_slash_are_normalized():
    for endpoint in (ACCOUNT.base_url + "/", ACCOUNT.base_url + "/v2/",
                     "  " + ACCOUNT.base_url + "/v2  "):
        equivalent = replace(ACCOUNT, base_url=endpoint)
        with _registry(ACCOUNT), accounts.use_account(equivalent):
            ok, note = guard.check_route(BOOK)
            assert ok is True, (endpoint, note)
        with _registry(equivalent), accounts.use_account(ACCOUNT):
            ok, note = guard.check_route(BOOK)
            assert ok is True, (endpoint, note)


def test_multi_account_registry_checks_requested_book_against_actual_binding():
    sibling = replace(ACCOUNT, account_id="acct2", account_key="sibling-book", key_id="B" * 26)
    with _registry(ACCOUNT, sibling):
        assert accounts.multi_account_active() is True
        with accounts.bind_for_user(sibling.account_key):
            _refused(BOOK)
            ok, note = guard.check_route(sibling.account_key)
            assert ok is True and note == "ok:acct2", (ok, note)
        with accounts.bind_for_user(BOOK):
            ok, note = guard.check_route(BOOK)
            assert ok is True and note == "ok:acct3", (ok, note)


if __name__ == "__main__":
    sys.exit(run_tests(globals()))
