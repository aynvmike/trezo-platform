"""Guard tests: a stop that lives at the venue must only ever tighten.

Why these exist (2026-08-18): every trailing stop in Trezo used to live
only in our ledger, enforced by the monitor watching the tape. That works
until the monitor stops watching, and on 8/17 it stopped for fifteen
hours while three books held positions. Stops now mirror to the broker,
where they keep working while we are down.

Which introduces a new way to lose money: a bug that moves a stop the
WRONG way. A stop that fails to tighten costs you some upside. A stop
that loosens itself costs you the position. These tests exist for the
second one.

Run: python -m agents.tests.test_broker_stop   (or pytest)
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _bootstrap import load_module, run_tests, stub_config  # noqa: E402

# alpaca.py reads settings at import. Stub them so these run in a bare
# checkout with no .env and no credentials -- a guard test nobody can
# run is a guard test nobody runs.
stub_config()

alp = load_module("app.brokers.alpaca")
ap = load_module("app.runtime.asset_policy")


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# Every stub below REPLACES a module attribute. Snapshot the real ones
# once at import so each test can start from the shipped code -- a stub
# that leaks into the next test is how a guard suite quietly stops
# guarding anything (it cost two false failures on 2026-08-18: the
# ratchet tests' fake replace_order was still installed when the
# replace_order plumbing tests ran, so they were testing the fake).
_REAL = {name: getattr(alp, name) for name in
         ("get_open_orders_for", "replace_order", "submit_oco_sell",
          "submit_stop_sell", "_patch")}


def _reset():
    for name, fn in _REAL.items():
        setattr(alp, name, fn)


def _fake_orders(orders):
    async def _f(symbol):
        return list(orders)
    alp.get_open_orders_for = _f


def _capture_replace():
    calls = []

    async def _f(order_id, **kw):
        calls.append((order_id, kw))
        return {"id": "new"}, None
    alp.replace_order = _f
    return calls


STOP_LEG = {"id": "leg-1", "type": "stop", "side": "sell", "stop_price": "88.00"}


# --- the invariant that matters ------------------------------------------

def test_a_stop_is_never_moved_down():
    _reset()
    _fake_orders([STOP_LEG])
    calls = _capture_replace()
    changed, note = _run(alp.ratchet_stop("GDX", 85.00, qty=3))
    assert changed is False, "moving a stop DOWN must be refused"
    assert not calls, "no amend should have been attempted"
    assert "already at" in note


def test_a_stop_moves_up():
    _reset()
    _fake_orders([STOP_LEG])
    calls = _capture_replace()
    changed, note = _run(alp.ratchet_stop("GDX", 91.50, qty=3))
    assert changed is True
    assert len(calls) == 1
    assert calls[0][0] == "leg-1"
    assert abs(calls[0][1]["stop_price"] - 91.50) < 1e-9


def test_an_equal_stop_is_not_rewritten():
    """Re-sending the same price every tick would churn the venue and
    burn rate limit for nothing."""
    _reset()
    _fake_orders([STOP_LEG])
    calls = _capture_replace()
    changed, _ = _run(alp.ratchet_stop("GDX", 88.00, qty=3))
    assert changed is False
    assert not calls


def test_a_failed_order_read_changes_nothing():
    """None means 'could not check'. Acting on it would be guessing."""
    _reset()
    async def _none(symbol):
        return None
    alp.get_open_orders_for = _none
    calls = _capture_replace()
    changed, note = _run(alp.ratchet_stop("GDX", 91.50, qty=3))
    assert changed is False
    assert not calls
    assert "could not read" in note


def test_a_naked_position_gets_protection_placed():
    """No stop at the venue is the dangerous case -- place one rather
    than report it and move on."""
    _reset()
    _fake_orders([])
    placed = []

    async def _oco(sym, qty, limit_price, stop_price):
        placed.append(("oco", sym, qty, limit_price, stop_price))
        return {"id": "oco-1"}, None
    alp.submit_oco_sell = _oco
    changed, note = _run(alp.ratchet_stop("GDX", 91.50, qty=3, target_price=99.0))
    assert changed is True
    assert placed and placed[0][0] == "oco"
    assert "no broker stop existed" in note


def test_a_buy_order_is_not_mistaken_for_a_stop_leg():
    """A resting BUY must never be amended as though it were our stop."""
    _reset()
    assert alp._is_stop_leg(STOP_LEG) is True
    assert alp._is_stop_leg(
        {"type": "stop", "side": "buy", "stop_price": "88"}) is False
    assert alp._is_stop_leg(
        {"type": "limit", "side": "sell", "limit_price": "99"}) is False


# --- the venue gate -------------------------------------------------------

def test_only_venues_that_hold_stops_are_synced():
    """Alpaca has no native stop for crypto. Syncing one would fail on
    every tick and teach us to ignore the error."""
    _reset()
    assert ap.policy_for("stock").native_brackets is True
    assert ap.policy_for("crypto").native_brackets is False


def test_replace_order_sends_only_what_changed():
    _reset()
    sent = {}

    async def _patch(path, body, token=None):
        sent["path"] = path
        sent["body"] = body
        return {}, None
    alp._patch = _patch
    _run(alp.replace_order("abc", stop_price=12.345))
    assert sent["path"] == "/v2/orders/abc"
    assert set(sent["body"]) == {"stop_price"}, (
        "sending fields the caller did not ask to change risks silently "
        "rewriting quantity or price")
    assert sent["body"]["stop_price"] == "12.35"


def test_replace_order_refuses_an_empty_change():
    _reset()
    _res, err = _run(alp.replace_order("abc"))
    assert _res is None and "nothing to change" in err


if __name__ == "__main__":
    sys.exit(run_tests(dict(globals())))
