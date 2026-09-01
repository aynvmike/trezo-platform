"""The XLE/BAC re-arm churn (2026-09-01): an OCO's stop leg is a nested child
order at Alpaca. Read flat, the stop is invisible and ensure_broker_stop
cancels-and-re-arms the pair every ten minutes. These tests drive the REAL
get_open_orders_for / ensure_broker_stop with a stubbed HTTP seam and pin
that a nested held stop leg is seen as protection.

Deploy-gate contract: plain test_ functions, no fixtures, no network.
"""
from contextlib import contextmanager
import asyncio

from tests import _bootstrap

_bootstrap.stub_config()
alpaca = _bootstrap.load_module("app.brokers.alpaca")


@contextmanager
def _patched(mod, **attrs):
    saved = {k: getattr(mod, k) for k in attrs}
    for k, v in attrs.items():
        setattr(mod, k, v)
    try:
        yield
    finally:
        for k, v in saved.items():
            setattr(mod, k, v)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


_OCO_PARENT = {
    "id": "p1", "symbol": "XLE", "type": "limit", "side": "sell",
    "status": "new", "qty": "12", "limit_price": "67.26",
    "legs": [
        {"id": "c1", "symbol": "XLE", "type": "stop", "side": "sell",
         "status": "held", "qty": "12", "stop_price": "60.86"},
    ],
}


def test_the_listing_asks_for_nested_legs():
    seen = []

    async def fake_get(path, **kw):
        seen.append(path)
        return [dict(_OCO_PARENT)]

    with _patched(alpaca, _get=fake_get):
        _run(alpaca.get_open_orders_for("xle"))
    assert seen and "nested=true" in seen[0] and "symbols=XLE" in seen[0]


def test_a_nested_held_stop_leg_is_returned_as_an_order():
    async def fake_get(path, **kw):
        return [dict(_OCO_PARENT)]

    with _patched(alpaca, _get=fake_get):
        orders = _run(alpaca.get_open_orders_for("XLE"))
    assert orders is not None
    types = sorted(str(o.get("type")) for o in orders)
    assert types == ["limit", "stop"], types
    assert any(alpaca._is_stop_leg(o) for o in orders)


def test_a_failed_listing_is_still_none_not_empty():
    async def fake_get(path, **kw):
        return None

    with _patched(alpaca, _get=fake_get):
        assert _run(alpaca.get_open_orders_for("XLE")) is None


def test_ensure_stock_protection_does_not_rearm_over_a_nested_stop():
    """The churn itself: with the stop only visible as a nested leg, the
    old code cancelled the target and re-placed the OCO every call."""
    deleted, submitted = [], []

    async def fake_get(path, **kw):
        return [dict(_OCO_PARENT)]

    async def fake_delete(path, **kw):
        deleted.append(path)
        return {}

    async def fake_oco(*a, **kw):
        submitted.append(("oco", a))
        return {}, None

    async def fake_stop(*a, **kw):
        submitted.append(("stop", a))
        return {}, None

    with _patched(alpaca, _get=fake_get, _delete=fake_delete,
                  submit_oco_sell=fake_oco, submit_stop_sell=fake_stop):
        changed, note = _run(alpaca.ensure_stock_protection("XLE", 12, 60.86, target=67.26))
    assert changed is False, note
    assert "already resting" in note
    assert deleted == [] and submitted == []


def test_a_lone_target_with_no_leg_is_still_replaced():
    lone = {k: v for k, v in _OCO_PARENT.items() if k != "legs"}
    deleted, submitted = [], []

    async def fake_get(path, **kw):
        return [lone]

    async def fake_delete(path, **kw):
        deleted.append(path)
        return {}

    async def fake_oco(*a, **kw):
        submitted.append("oco")
        return {}, None

    async def fake_stop(*a, **kw):
        submitted.append("stop")
        return {}, None

    with _patched(alpaca, _get=fake_get, _delete=fake_delete,
                  submit_oco_sell=fake_oco, submit_stop_sell=fake_stop):
        changed, note = _run(alpaca.ensure_stock_protection("XLE", 12, 60.86, target=67.26))
    assert changed is True and "replaced a lone resting target" in note
    assert deleted == ["/v2/orders/p1"] and submitted == ["oco"]


# --- Review 2026-09-01 (R-NESTED-1/2): the flattened list must not lie -----

def test_a_leg_listed_twice_is_returned_once():
    """If the venue ever lists the stop BOTH at top level and under the
    parent's legs, ratchet_stop must see one leg, not two (one amend,
    one cancel-by-id, one quantity)."""
    child = dict(_OCO_PARENT["legs"][0])
    parent = dict(_OCO_PARENT)

    async def fake_get(path, **kw):
        return [parent, dict(child)]

    with _patched(alpaca, _get=fake_get):
        orders = _run(alpaca.get_open_orders_for("XLE"))
    ids = [o.get("id") for o in orders]
    assert ids == ["p1", "c1"], ids
    assert sum(1 for o in orders if alpaca._is_stop_leg(o)) == 1


def test_a_replaced_or_cancelled_child_leg_is_not_protection():
    """After ratchet_stop PATCHes the stop, Alpaca issues a new leg id
    and marks the old one `replaced`. The dead leg must not be the one
    the next ratchet tries to amend, and a `canceled` leg is not a
    resting stop."""
    dead = {"id": "c-old", "symbol": "XLE", "type": "stop", "side": "sell",
            "status": "replaced", "qty": "12", "stop_price": "60.00"}
    live = {"id": "c-new", "symbol": "XLE", "type": "stop", "side": "sell",
            "status": "held", "qty": "12", "stop_price": "61.00"}
    parent = dict(_OCO_PARENT, legs=[dead, live])
    amended = []

    async def fake_get(path, **kw):
        return [parent]

    async def fake_replace(order_id, **kw):
        amended.append((order_id, kw))
        return {"id": "c-newer"}, None

    with _patched(alpaca, _get=fake_get, replace_order=fake_replace):
        orders = _run(alpaca.get_open_orders_for("XLE"))
        stops = [o["id"] for o in orders if alpaca._is_stop_leg(o)]
        assert stops == ["c-new"], stops
        changed, note = _run(alpaca.ratchet_stop("XLE", 62.00, qty=12))
    assert changed is True, note
    assert amended and amended[0][0] == "c-new", amended

    only_dead = dict(_OCO_PARENT, legs=[dict(dead, status="canceled")])

    async def fake_get2(path, **kw):
        return [only_dead]

    with _patched(alpaca, _get=fake_get2):
        orders = _run(alpaca.get_open_orders_for("XLE"))
    assert not any(alpaca._is_stop_leg(o) for o in orders), orders


def test_a_held_leg_with_no_status_is_still_kept():
    """Only a TERMINAL status drops a leg; a missing status must not."""
    leg = {k: v for k, v in _OCO_PARENT["legs"][0].items() if k != "status"}
    parent = dict(_OCO_PARENT, legs=[leg])

    async def fake_get(path, **kw):
        return [parent]

    with _patched(alpaca, _get=fake_get):
        orders = _run(alpaca.get_open_orders_for("XLE"))
    assert any(alpaca._is_stop_leg(o) for o in orders)


if __name__ == "__main__":
    import sys
    sys.exit(_bootstrap.run_tests(dict(vars())))
