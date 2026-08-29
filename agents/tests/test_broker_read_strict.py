"""Guards for the 2026-08-28 phantom-close loop.

The case these replay is real: the 75k book's broker held AMZN, DOT and
QYLD while the ledger kept closing them. The phantom was in the CLOSES.
A FAILED positions read (429/timeout/5xx) came back as [] --
indistinguishable from a flat account -- book_scope cached that as
broker truth, and Position Monitor read "symbol gone at broker" as "the
bracket filled", closing every broker-held row at modeled prices. The
reconciler re-adopted them and the loop booked ~-$5.8k of realized P/L
on DOT alone that never happened at the broker.

Second bug, same loop: the ledger's 8-decimal quantity rounded UP past
the broker's 9-decimal holding, so every crypto stop 403'd
"insufficient balance" and $10.9k of coin rode with no floor.

What matters here is the ASYMMETRY, the same one broker_truth.py is
built on: an answerless read must never be readable as an answer.

Deliberately dependency-free (no pytest, no .env, no network) so the
deploy guard can run them in a bare checkout.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _bootstrap import load_module, run_tests, stub_config  # noqa: E402

stub_config()
alp = load_module("app.brokers.alpaca")
book_scope = load_module("app.runtime.book_scope")


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@contextlib.contextmanager
def _patched(mod, **attrs):
    """Swap module attributes and always put the originals back."""
    old = {k: getattr(mod, k, None) for k in attrs}
    try:
        for k, v in attrs.items():
            setattr(mod, k, v)
        yield
    finally:
        for k, v in old.items():
            if v is None:
                if hasattr(mod, k):
                    delattr(mod, k)
            else:
                setattr(mod, k, v)


# --- the strict read -----------------------------------------------------

def test_a_failed_read_is_none_not_empty():
    async def _fail(path, token=None):
        return None                  # what _get yields on 429/timeout/5xx
    with _patched(alp, _get=_fail):
        assert _run(alp.get_positions_strict()) is None


def test_a_real_answer_passes_through():
    rows = [{"symbol": "DOTUSD", "qty": "13060.384624917"}]

    async def _ok(path, token=None):
        return rows
    with _patched(alp, _get=_ok):
        assert _run(alp.get_positions_strict()) == rows


def test_an_empty_account_is_still_an_empty_list():
    """Flat is an ANSWER. Only a failure is answerless."""
    async def _flat(path, token=None):
        return []
    with _patched(alp, _get=_flat):
        assert _run(alp.get_positions_strict()) == []


def test_the_plain_read_keeps_its_old_shape():
    async def _fail(path, token=None):
        return None
    with _patched(alp, _get=_fail):
        assert _run(alp.get_positions()) == []


# --- book_scope: the cache that fed the loop -----------------------------

def test_book_scope_reports_a_failed_read_as_could_not_check():
    calls = {"n": 0}

    async def _boom():
        calls["n"] += 1
        return None

    book_scope.new_cycle()
    with _patched(book_scope, _fetch_positions=_boom,
                  bind=lambda uid, where="": contextlib.nullcontext("book")):
        assert _run(book_scope.held_symbols("book-a", where="guard")) is None
        # AND it is not cached: a failure must not be replayed as truth
        _run(book_scope.held_symbols("book-a", where="guard"))
        assert calls["n"] == 2, calls
    book_scope.new_cycle()


def test_book_scope_still_answers_when_the_broker_answers():
    async def _rows():
        return [{"symbol": "AMZN"}, {"symbol": "QYLD"}]

    book_scope.new_cycle()
    with _patched(book_scope, _fetch_positions=_rows,
                  bind=lambda uid, where="": contextlib.nullcontext("book")):
        got = _run(book_scope.held_symbols("book-b", where="guard"))
        assert got == {"AMZN", "QYLD"}, got
    book_scope.new_cycle()


# --- the stop quantity ---------------------------------------------------

def test_a_crypto_stop_carries_the_brokers_own_quantity():
    """Ledger 13060.38462492 (8dp, rounded UP) vs broker
    13060.384624917. Ask for ours and Alpaca 403s; the coin then rides
    with no floor, which is exactly what happened to DOT."""
    posted = {}

    async def _no_orders(sym):
        return []

    async def _get(path, token=None):
        assert "/v2/positions/" in path, path
        return {"qty": "13060.384624917"}

    async def _post(path, body, token=None):
        posted.update(body)
        return {"id": "ord-1"}, None

    with _patched(alp, open_crypto_orders=_no_orders, _get=_get, _post=_post):
        ok, note = _run(alp.ratchet_crypto_stop("DOT", 0.7999,
                                                qty=13060.38462492))
    assert ok, note
    assert posted.get("qty") == "13060.384624917", posted


def test_a_stop_is_still_placed_when_the_venue_read_fails():
    """A 403 retry next tick beats silently skipping protection."""
    posted = {}

    async def _no_orders(sym):
        return []

    async def _get(path, token=None):
        return None

    async def _post(path, body, token=None):
        posted.update(body)
        return {"id": "ord-2"}, None

    with _patched(alp, open_crypto_orders=_no_orders, _get=_get, _post=_post):
        ok, note = _run(alp.ratchet_crypto_stop("DOT", 0.7999, qty=5.0))
    assert ok, note
    assert posted.get("qty") == "5.0", posted


if __name__ == "__main__":
    sys.exit(run_tests(dict(vars())))
