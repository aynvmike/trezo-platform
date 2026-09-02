"""Shorts are policy (Mike, 2026-09-02: "let the agents maintain it"), so the
agents must protect them at the venue exactly like longs. These tests drive
the REAL ensure_short_protection and the REAL _arm_broker_stop with the HTTP
and market-clock seams stubbed and restored. Deploy-gate contract: plain
zero-arg test_ functions, no fixtures, no network, no .env.
"""
from contextlib import contextmanager
import asyncio

from tests import _bootstrap

_bootstrap.stub_config()
alpaca = _bootstrap.load_module("app.brokers.alpaca")
pm = _bootstrap.load_module("app.agents.position_monitor")
wd = _bootstrap.load_module("app.agents.ops_watchdog")
alog = _bootstrap.load_module("app.agents.activity_log")


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


_LONE_TP = {"id": "tp1", "symbol": "XLF", "type": "limit", "side": "buy",
            "status": "new", "qty": "340", "limit_price": "57.04"}


def _http(orders, position_qty="-340"):
    async def fake_get(path, **kw):
        if path.startswith("/v2/orders"):
            return list(orders)
        if path.startswith("/v2/positions/"):
            return {"symbol": "XLF", "qty": position_qty}
        return None
    return fake_get


def test_a_lone_buy_limit_is_replaced_by_a_buy_oco_with_stop_above_and_target_below():
    deleted, posted = [], []

    async def fake_delete(path, **kw):
        deleted.append(path)
        return {}

    async def fake_post(path, body, **kw):
        posted.append(body)
        return {"id": "oco1"}, None

    with _patched(alpaca, _get=_http([_LONE_TP]), _delete=fake_delete, _post=fake_post):
        changed, note = _run(alpaca.ensure_short_protection("XLF", 340, 57.98, target=57.04))
    assert changed is True, note
    assert deleted == ["/v2/orders/tp1"]
    body = posted[0]
    assert body["side"] == "buy" and body["order_class"] == "oco"
    assert body["take_profit"]["limit_price"] == "57.04"
    assert body["stop_loss"]["stop_price"] == "57.98"
    assert body["qty"] == "340"


def test_a_resting_buy_stop_means_nothing_is_touched():
    stop_leg = {"id": "s1", "symbol": "XLF", "type": "stop", "side": "buy", "status": "held", "qty": "340"}
    posted = []

    async def fake_post(path, body, **kw):
        posted.append(body)
        return {}, None

    with _patched(alpaca, _get=_http([_LONE_TP, stop_leg]), _post=fake_post):
        changed, note = _run(alpaca.ensure_short_protection("XLF", 340, 57.98, target=57.04))
    assert changed is False and "already resting" in note
    assert posted == []


def test_an_oco_refusal_falls_back_to_a_plain_buy_stop():
    posted = []

    async def fake_delete(path, **kw):
        return {}

    async def fake_post(path, body, **kw):
        posted.append(body)
        if body.get("order_class") == "oco":
            return None, "oco refused"
        return {"id": "stop1"}, None

    with _patched(alpaca, _get=_http([_LONE_TP]), _delete=fake_delete, _post=fake_post):
        changed, note = _run(alpaca.ensure_short_protection("XLF", 340, 57.98, target=57.04))
    assert changed is True and "buy stop" in note, note
    assert posted[-1]["type"] == "stop" and posted[-1]["side"] == "buy"


def test_when_both_are_refused_the_lone_target_is_restored():
    posted = []

    async def fake_delete(path, **kw):
        return {}

    async def fake_post(path, body, **kw):
        posted.append(body)
        if body.get("order_class") == "oco" or body.get("type") == "stop":
            return None, "refused"
        return {"id": "restored"}, None

    with _patched(alpaca, _get=_http([_LONE_TP]), _delete=fake_delete, _post=fake_post):
        changed, note = _run(alpaca.ensure_short_protection("XLF", 340, 57.98, target=57.04))
    assert changed is False and "restored" in note, note
    assert posted[-1]["type"] == "limit" and posted[-1]["side"] == "buy" and posted[-1]["limit_price"] == "57.04"


def test_a_failed_order_listing_arms_nothing():
    async def none_get(path, **kw):
        return None

    with _patched(alpaca, _get=none_get):
        changed, note = _run(alpaca.ensure_short_protection("XLF", 340, 57.98, target=57.04))
    assert changed is False and "left untouched" in note


def test_the_monitor_arms_a_short_row_through_the_short_helper():
    calls = []

    async def fake_short(tk, qty, stop, target=None):
        calls.append(("short", tk, qty, stop, target))
        return True, "short had no broker stop - placed buy OCO"

    async def fake_long(tk, qty, stop, target=None):
        calls.append(("long", tk, qty, stop, target))
        return True, "placed"

    row = {"id": "r1", "user_id": "u1", "ticker": "XLF", "side": "short", "broker": "alpaca",
           "asset_type": "stock", "quantity": 340, "stop_price": 57.98, "target_price": 57.04}
    with _patched(alpaca, ensure_short_protection=fake_short, ensure_stock_protection=fake_long), \
         _patched(wd, _us_market_open=lambda: True), \
         _patched(alog, record=lambda *a, **k: None), \
         _patched(pm, _stop_armed_at={}):
        _run(pm._arm_broker_stop(row))
        row2 = dict(row, id="r2", side="long", stop_price=56.0, target_price=59.0, ticker="XLE")
        _run(pm._arm_broker_stop(row2))
    assert calls[0][0] == "short" and calls[0][1] == "XLF" and calls[0][3] == 57.98 and calls[0][4] == 57.04, calls
    assert calls[1][0] == "long" and calls[1][1] == "XLE", calls


def test_a_crypto_short_row_is_never_armed():
    calls = []

    async def fake_short(*a, **k):
        calls.append(a)
        return True, "x"

    row = {"id": "r3", "user_id": "u1", "ticker": "DOTUSD", "side": "short", "broker": "alpaca",
           "asset_type": "crypto", "quantity": 10, "stop_price": 5.0, "target_price": 4.0}
    with _patched(alpaca, ensure_short_protection=fake_short), _patched(alog, record=lambda *a, **k: None), \
         _patched(pm, _stop_armed_at={}):
        out = _run(pm._arm_broker_stop(row))
    assert out is None and calls == []
