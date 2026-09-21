"""Explicit snapshots must read the requested book, never a fallback book.

Runs real registry binding, Alpaca header selection and account parsing;
only the broker response and OAuth lookup are replaced. No network or
credentials are required, and main.py is not imported/booted.
"""
from __future__ import annotations

import ast
import asyncio
import contextlib
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import load_module, run_tests, stub_config

stub_config()
active = load_module("app.brokers.active")
accounts = load_module("app.brokers.accounts")
alp = load_module("app.brokers.alpaca")
tokens = load_module("app.integrations.web_tokens")

BOOKS = [accounts.BrokerAccount(
    account_id=slot, label=slot, owner_id="one-owner", account_key=f"book-{i}",
    key_id=str(i) * 26, secret=str(i) * 44,
) for i, slot in enumerate(("primary", "acct2", "acct3"), 1)]


def _payload(equity=100):
    return {"id": "broker-account", "equity": str(equity), "cash": "25",
            "last_equity": "101", "buying_power": "50"}


@contextlib.contextmanager
def _reads(*, books=None, payload=None, fail=False, token=None, token_error=False):
    calls = []
    oauth_calls = []

    async def lookup(user_id, broker):
        oauth_calls.append((user_id, broker))
        if token_error:
            raise RuntimeError("token lookup unavailable")
        return token

    async def response(path, token=None):
        # The actual Alpaca transport selects credentials at this seam.
        before = alp._headers_for(token)
        await asyncio.sleep(0)
        assert alp._headers_for(token) == before, "concurrent account leaked"
        calls.append((path, before))
        return None if fail else (payload if payload is not None else _payload())

    with patch.object(accounts, "load_accounts", return_value=BOOKS if books is None else books), \
            patch.object(alp, "_live_active", return_value=False), \
            patch.object(tokens, "get_user_broker_token", lookup), \
            patch.object(alp, "_get", response):
        yield calls, oauth_calls


def test_three_concurrent_books_use_three_credential_sets():
    async def read_all():
        with accounts.use_account(BOOKS[0]):
            snapshots = await asyncio.gather(*[
                active.active_broker_snapshot(book.account_key) for book in BOOKS])
            assert accounts.current_account() == BOOKS[0]
            return snapshots

    with _reads() as (calls, oauth):
        snapshots = asyncio.run(read_all())
    assert [s.book_key for s in snapshots] == [b.account_key for b in BOOKS]
    assert {c[1]["APCA-API-KEY-ID"] for c in calls} == {b.key_id for b in BOOKS}
    assert not oauth, "a registered book must not resolve its owner's OAuth"


def test_unknown_explicit_book_does_not_inherit_outer_binding():
    with _reads() as (calls, _):
        with accounts.use_account(BOOKS[2]):
            assert asyncio.run(active.active_broker_snapshot("unknown-book")) is None
            assert accounts.current_account() == BOOKS[2]
    assert not calls


def test_failed_oauth_lookup_never_uses_env_credentials():
    with _reads(token_error=True) as (calls, _):
        assert asyncio.run(active.active_broker_snapshot("oauth-owner")) is None
    assert not calls


def test_connected_oauth_owner_uses_bearer_token():
    token = tokens.BrokerToken(access_token="fixture-oauth-token")
    with _reads(token=token) as (calls, _):
        snap = asyncio.run(active.active_broker_snapshot("oauth-owner"))
    assert snap and snap.book_key is None
    assert calls == [("/v2/account", {"Authorization": "Bearer fixture-oauth-token"})]


def test_token_disappearing_after_broker_selection_never_falls_back():
    n = 0

    async def token_once(user_id, broker):
        nonlocal n
        n += 1
        return tokens.BrokerToken("fixture-token") if n == 1 else None

    with _reads() as (calls, _), patch.object(tokens, "get_user_broker_token", token_once):
        assert asyncio.run(active.active_broker_snapshot("oauth-owner")) is None
    assert not calls


def test_unreadable_account_is_none_not_zero_and_context_restores():
    with _reads(fail=True):
        with accounts.use_account(BOOKS[0]):
            assert asyncio.run(active.active_broker_snapshot(BOOKS[1].account_key)) is None
            assert accounts.current_account() == BOOKS[0]


def test_raised_account_error_restores_binding_and_returns_none():
    async def broken(token=None):
        assert accounts.current_account() == BOOKS[1]
        raise RuntimeError("read failed")

    with _reads(), patch.object(alp, "get_account", broken):
        with accounts.use_account(BOOKS[0]):
            assert asyncio.run(active.active_broker_snapshot(BOOKS[1].account_key)) is None
            assert accounts.current_account() == BOOKS[0]


def test_cancelled_read_propagates_and_restores_binding():
    async def cancelled(token=None):
        assert accounts.current_account() == BOOKS[1]
        raise asyncio.CancelledError()

    async def check():
        with accounts.use_account(BOOKS[0]):
            try:
                await active.active_broker_snapshot(BOOKS[1].account_key)
                raise AssertionError("cancellation was swallowed")
            except asyncio.CancelledError:
                assert accounts.current_account() == BOOKS[0]

    with _reads(), patch.object(alp, "get_account", cancelled):
        asyncio.run(check())


def test_valid_zero_equity_remains_zero():
    with _reads(payload=_payload(0)):
        snap = asyncio.run(active.active_broker_snapshot(BOOKS[1].account_key))
    assert snap is not None and snap.equity == 0
    assert snap.cash == 25, "cash and equity are different broker fields"


def test_nonfinite_equity_or_cash_cannot_report_success():
    for field in ("equity", "cash", "last_equity", "buying_power"):
        for value in ("nan", "inf", "-inf"):
            payload = _payload()
            payload[field] = value
            with _reads(payload=payload):
                assert asyncio.run(active.active_broker_snapshot(BOOKS[1].account_key)) is None


def test_single_secondary_registry_cannot_use_primary_transport():
    # Existing Alpaca transport ignores registry in single-account mode.
    with _reads(books=[BOOKS[1]]) as (calls, _):
        assert asyncio.run(active.active_broker_snapshot(BOOKS[1].account_key)) is None
    assert not calls


def test_paper_book_request_cannot_be_labeled_with_live_account():
    with _reads() as (calls, _), patch.object(alp, "_live_active", return_value=True):
        assert asyncio.run(active.active_broker_snapshot(BOOKS[1].account_key)) is None
    assert not calls


def test_implicit_snapshot_retains_current_account_route():
    with _reads() as (calls, _):
        with accounts.use_account(BOOKS[2]):
            snap = asyncio.run(active.active_broker_snapshot())
    assert snap is not None and snap.book_key is None
    assert calls[0][1] == BOOKS[2].headers()


def _endpoint():
    path = Path(__file__).resolve().parents[1] / "app" / "main.py"
    source = path.read_text(encoding="utf-8")
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.AsyncFunctionDef)
                and n.name == "broker_snapshot_endpoint")
    ns = {}
    exec(compile(ast.get_source_segment(source, node), str(path), "exec"), ns)
    return ns[node.name]


def test_endpoint_failure_has_null_snapshot_and_no_modeled_success():
    with _reads(fail=True):
        result = asyncio.run(_endpoint()(BOOKS[1].account_key))
    assert result["ok"] is False
    assert result["snapshot"] is None
    assert result["read_status"] == "unavailable"
    assert result["requested_book"] == BOOKS[1].account_key


def test_endpoint_echoes_verified_book_and_real_equity():
    with _reads(payload=_payload(321)):
        result = asyncio.run(_endpoint()(BOOKS[1].account_key))
    assert result["ok"] is True and result["book_key"] == BOOKS[1].account_key
    assert result["snapshot"]["equity"] == 321
    assert result["snapshot"]["cash"] == 25


if __name__ == "__main__":
    raise SystemExit(run_tests(globals()))
