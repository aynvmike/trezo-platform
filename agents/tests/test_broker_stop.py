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
    # Close the loop each time: leaking one per call makes CPython spew
    # a GC traceback AFTER the results print, which reads like a failure
    # in a suite that passed.
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# Every stub below REPLACES a module attribute. Snapshot the real ones
# once at import so each test can start from the shipped code -- a stub
# that leaks into the next test is how a guard suite quietly stops
# guarding anything (it cost two false failures on 2026-08-18: the
# ratchet tests' fake replace_order was still installed when the
# replace_order plumbing tests ran, so they were testing the fake).
_REAL = {name: getattr(alp, name) for name in
         ("get_open_orders_for", "replace_order", "submit_oco_sell",
          "submit_stop_sell", "_patch", "_delete", "_post")}


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


# --- arming a stop that was never there -----------------------------------
# The naked-position check asks "are there any open orders". Mike found
# the case that slips past it on 8/18: GDX on the 25k book with a resting
# sell limit at 94 and nothing under it. One order, so it read as
# protected. A lone target is upside with no floor.

TARGET_ONLY = {"id": "tgt-1", "type": "limit", "side": "sell",
               "limit_price": "94.00", "qty": "3"}


def _capture_protection():
    placed, deleted, posted = [], [], []

    async def _oco(sym, qty, limit_price, stop_price):
        placed.append(("oco", sym, qty, limit_price, stop_price))
        return {"id": "oco-1"}, None

    async def _stop(sym, qty, stop_price):
        placed.append(("stop", sym, qty, stop_price))
        return {"id": "stop-1"}, None

    async def _del(path, token=None):
        deleted.append(path)
        return {}, None

    async def _post(path, body, token=None):
        posted.append(body)
        return {"id": "re-1"}, None

    alp.submit_oco_sell, alp.submit_stop_sell, alp._delete = _oco, _stop, _del
    alp._post = _post
    return placed, deleted, posted


def test_a_lone_resting_target_is_not_mistaken_for_protection():
    _reset()
    _fake_orders([TARGET_ONLY])
    placed, deleted, _posted = _capture_protection()
    changed, note = _run(alp.ensure_stock_protection("GDX", 3, 88.0, 94.0))
    assert changed is True, note
    assert deleted == ["/v2/orders/tgt-1"], (
        "the target reserves the same shares the stop needs")
    assert placed and placed[0][0] == "oco"
    assert placed[0][3] == 94.0 and placed[0][4] == 88.0


def test_an_existing_stop_is_left_alone():
    """Placing a second stop would double-sell the position. This is why
    the June check was alert-only; reading the book first is what makes
    placing safe."""
    _reset()
    _fake_orders([STOP_LEG])
    placed, deleted, _posted = _capture_protection()
    changed, _ = _run(alp.ensure_stock_protection("GDX", 3, 91.0, 99.0))
    assert changed is False
    assert not placed and not deleted


def test_a_refused_oco_still_leaves_a_stop():
    """Protection first (2026-07-15, the PYPL naked-4 incident). A lost
    target costs upside; a lost stop costs the position."""
    _reset()
    _fake_orders([])
    placed, _deleted, _posted = _capture_protection()

    async def _refuse(sym, qty, limit_price, stop_price):
        return None, "HTTP 422: insufficient qty"
    alp.submit_oco_sell = _refuse

    changed, note = _run(alp.ensure_stock_protection("GDX", 3, 88.0, 94.0))
    assert changed is True
    assert placed and placed[0][0] == "stop" and placed[0][3] == 88.0
    assert "target NOT restored" not in note, "nothing was cancelled here"


def test_a_failed_order_read_arms_nothing():
    _reset()

    async def _none(symbol):
        return None
    alp.get_open_orders_for = _none
    placed, deleted, _posted = _capture_protection()
    changed, note = _run(alp.ensure_stock_protection("GDX", 3, 88.0, 94.0))
    assert changed is False
    assert not placed and not deleted
    assert "could not read" in note


def test_arming_without_a_stop_price_does_nothing():
    """A row with no stop is a data problem, not a licence to invent a
    level and sell against it."""
    _reset()
    _fake_orders([])
    placed, _d, _posted = _capture_protection()
    changed, _ = _run(alp.ensure_stock_protection("GDX", 3, 0.0, 94.0))
    assert changed is False and not placed


def test_a_position_is_never_left_with_nothing_resting():
    """The failure mode this whole function could have created: ledger
    qty larger than what the broker holds, so every sell is rejected --
    but the lone target was cancelled on the way in. Walking away there
    leaves the position with NO orders at all, strictly worse than the
    target we set out to improve on."""
    _reset()
    _fake_orders([TARGET_ONLY])
    placed, deleted, posted = _capture_protection()

    async def _reject_oco(sym, qty, limit_price, stop_price):
        return None, "HTTP 403: insufficient qty available"

    async def _reject_stop(sym, qty, stop_price):
        return None, "HTTP 403: insufficient qty available"
    alp.submit_oco_sell, alp.submit_stop_sell = _reject_oco, _reject_stop

    changed, note = _run(alp.ensure_stock_protection("GDX", 99, 88.0, 94.0))
    assert changed is False
    assert deleted == ["/v2/orders/tgt-1"]
    assert len(posted) == 1, "the cancelled target must be put back"
    assert posted[0]["side"] == "sell" and posted[0]["type"] == "limit"
    assert float(posted[0]["limit_price"]) == 94.0
    assert float(posted[0]["qty"]) == 3.0, (
        "restore the ORDER's original quantity, not the ledger's")
    assert "target restored" in note


# --- the venue gate -------------------------------------------------------

def test_a_venue_is_asked_for_the_stop_type_it_actually_takes():
    """Rewritten 2026-08-18. This test used to assert "crypto gets no
    stop" and read as settled fact for two months. Half true: crypto
    gets no BRACKET, but it does take a stop_limit on gtc, and while
    this test passed, real coins were riding with nothing behind them.

    A test can encode a wrong belief as confidently as a right one. The
    question is now the useful one -- which order type, not whether."""
    _reset()
    assert ap.policy_for("stock").native_brackets is True
    assert ap.policy_for("crypto").native_brackets is False, (
        "still no OCO for crypto -- that part was right")
    assert ap.policy_for("stock").stop_order_type == "stop"
    assert ap.policy_for("crypto").stop_order_type == "stop_limit"


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
