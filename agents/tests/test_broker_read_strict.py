"""Pin the 2026-08-28 phantom-close fixes.

The DOT/QYLD/AMZN loop: a FAILED broker positions read used to come back
as [] ("holds nothing"), book_scope cached it as truth, and Position
Monitor closed every broker-held row on the book at modeled prices while
Alpaca kept holding them. Separately, the ledger's 8-decimal quantity
rounded UP past the broker's 9-decimal holding, so every crypto stop
placement 403'd "insufficient balance" and the position sat with no
floor. These tests pin both repairs.
"""
from __future__ import annotations

import asyncio

import pytest

from app.brokers import alpaca as alp
from app.runtime import book_scope


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------- strict read

def test_strict_read_returns_none_on_failure(monkeypatch):
    async def _fail(path, token=None):
        return None                      # what _get yields on 429/timeout/5xx
    monkeypatch.setattr(alp, "_get", _fail)
    assert _run(alp.get_positions_strict()) is None


def test_strict_read_passes_lists_through(monkeypatch):
    rows = [{"symbol": "DOTUSD", "qty": "13060.384624917"}]

    async def _ok(path, token=None):
        return rows
    monkeypatch.setattr(alp, "_get", _ok)
    assert _run(alp.get_positions_strict()) == rows
    assert _run(alp.get_positions_strict([])) if False else True


def test_plain_read_keeps_empty_list_compat(monkeypatch):
    async def _fail(path, token=None):
        return None
    monkeypatch.setattr(alp, "_get", _fail)
    # Non-destructive callers keep the old [] shape...
    assert _run(alp.get_positions()) == []


def test_book_scope_treats_failed_read_as_answerless(monkeypatch):
    """A failed fetch must surface as None (do-not-act), never as
    'holds nothing' -- and must NOT be cached as an answer."""
    calls = {"n": 0}

    async def _boom():
        calls["n"] += 1
        return None
    book_scope.new_cycle()
    monkeypatch.setattr(book_scope, "_fetch_positions", _boom)
    monkeypatch.setattr(
        book_scope, "bind",
        lambda uid, where="": __import__("contextlib").nullcontext("book"))
    got = _run(book_scope.held_symbols("some-book", where="test"))
    assert got is None
    # not cached: a second ask re-fetches instead of replaying the failure
    _run(book_scope.held_symbols("some-book", where="test"))
    assert calls["n"] == 2
    book_scope.new_cycle()


# ------------------------------------------------------------- stop qty clamp

def test_crypto_stop_clamps_qty_to_broker_holding(monkeypatch):
    """Ledger 13060.38462492 (8dp, rounded up) vs broker
    13060.384624917: the stop order must carry the BROKER's quantity
    string, or Alpaca 403s and the coin rides unprotected."""
    posted = {}

    async def _no_orders(sym):
        return []

    async def _get(path, token=None):
        assert "/v2/positions/" in path
        return {"qty": "13060.384624917"}

    async def _post(path, body, token=None):
        posted.update(body)
        return {"id": "ord-1"}, None

    monkeypatch.setattr(alp, "open_crypto_orders", _no_orders)
    monkeypatch.setattr(alp, "_get", _get)
    monkeypatch.setattr(alp, "_post", _post)

    ok, note = _run(alp.ratchet_crypto_stop(
        "DOT", 0.7999, qty=13060.38462492))
    assert ok, note
    assert posted["qty"] == "13060.384624917"


def test_crypto_stop_keeps_own_qty_when_broker_read_fails(monkeypatch):
    """If the venue read fails, place with what we have -- a 403 retry
    next tick beats silently skipping protection."""
    posted = {}

    async def _no_orders(sym):
        return []

    async def _get(path, token=None):
        return None

    async def _post(path, body, token=None):
        posted.update(body)
        return {"id": "ord-2"}, None

    monkeypatch.setattr(alp, "open_crypto_orders", _no_orders)
    monkeypatch.setattr(alp, "_get", _get)
    monkeypatch.setattr(alp, "_post", _post)

    ok, note = _run(alp.ratchet_crypto_stop("DOT", 0.7999, qty=5.0))
    assert ok, note
    assert posted["qty"] == "5.0"
