"""Broker exits use fresh sided quotes and verified execution receipts.

These regressions drive the real monitor/helper with external seams replaced.
No credentials, .env, external requests, broker orders or activity-log writes.
Every module replacement is restored, including in the shared run_all process.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import load_module, run_tests, stub_config  # noqa: E402

stub_config()
policy = load_module("app.runtime.asset_policy")
scope = load_module("app.runtime.book_scope")
settings = load_module("app.runtime.settings")
accounts = load_module("app.brokers.accounts")
route = load_module("app.brokers.route_guard")
alp = load_module("app.brokers.alpaca")
data = load_module("app.brokers.alpaca_data")
log = load_module("app.agents.activity_log")
engine = load_module("app.paper.engine")
pm = load_module("app.agents.position_monitor")


def _run(coro):
    return asyncio.run(coro)


@contextlib.contextmanager
def _patched(mod, **attrs):
    missing = object()
    old = {key: getattr(mod, key, missing) for key in attrs}
    try:
        for key, value in attrs.items():
            setattr(mod, key, value)
        yield
    finally:
        for key, value in old.items():
            if value is missing:
                if hasattr(mod, key):
                    delattr(mod, key)
            else:
                setattr(mod, key, value)


def _iso(**ago):
    return (datetime.now(timezone.utc) - timedelta(**ago)).isoformat()


def _row(book="book-a", **overrides):
    row = {
        "id": "sol-" + book, "user_id": book, "ticker": "SOL",
        "asset_type": "crypto", "broker": "alpaca", "side": "long",
        "quantity": 2.0, "entry_price": 150.0,
        "stop_price": 140.0, "target_price": 200.0,
        "entry_at": _iso(hours=1), "strategy": "crypto_swing",
        "status": "open", "close_requested": False, "source_payload": {},
    }
    row.update(overrides)
    return row


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, client, table):
        self.client, self.table = client, table
        self.filters, self.payload, self.single = [], None, False

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, field, value):
        self.filters.append((field, value))
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def maybe_single(self):
        self.single = True
        return self

    def update(self, payload):
        self.payload = dict(payload)
        return self

    def execute(self):
        rows = [row for row in self.client.rows.get(self.table, [])
                if all(row.get(key) == value for key, value in self.filters)]
        if self.payload is not None:
            self.client.updates.append((self.table, self.filters, self.payload))
            for row in rows:
                row.update(self.payload)
        return _Result((rows[0] if rows else None) if self.single else rows)


class _Client:
    def __init__(self, rows):
        self.rows = {"paper_positions": rows}
        self.updates = []

    def table(self, name):
        return _Query(self, name)


@contextlib.contextmanager
def _registry():
    books = [accounts.BrokerAccount(
        account_id=book, label=book, owner_id="owner", account_key=book,
        key_id=key * 26, secret=secret * 44)
        for book, key, secret in (("book-a", "K", "S"), ("book-b", "L", "T"))]
    by_key = {book.account_key: book for book in books}
    lookup = lambda key: by_key.get(str(key or ""))
    skip = lambda key: lookup(key) is None
    with _patched(accounts, load_accounts=lambda: books,
                  account_for_user=lookup, primary_account=lambda: books[0],
                  multi_account_active=lambda: True,
                  should_skip_unresolved=skip), \
            _patched(route, load_accounts=lambda: books,
                     account_for_user=lookup, multi_account_active=lambda: True), \
            _patched(pm, _pm_skip_unresolved=skip):
        accounts.clear_account()
        try:
            yield
        finally:
            accounts.clear_account()


def _bound_book():
    bound = accounts.current_account()
    return bound.account_key if bound else None


async def _noop(*_args, **_kwargs):
    return None


async def _no_candles(*_args, **_kwargs):
    raise AssertionError("broker exit must never read historical candles")


async def _no_modeled_close(*_args, **_kwargs):
    raise AssertionError("broker exit must never book a modeled close")


def _quote(symbol="SOL/USD", bid=149.5, ask=150.5, ts=None):
    return data.Quote(symbol=symbol, bid=bid, ask=ask, bid_size=5,
                      ask_size=5, ts=ts or _iso(seconds=1))


def test_exit_quotes_use_executable_side_and_keep_provenance():
    pricing = load_module("app.brokers.execution_price")
    candles = load_module("app.data.candles")
    now = datetime(2026, 9, 18, 13, 0, tzinfo=timezone.utc)
    quote = _quote(ts=(now - timedelta(seconds=5)).isoformat())
    calls = []

    async def _read(symbol):
        calls.append(symbol)
        return quote

    with _patched(data, get_crypto_quote=_read), \
            _patched(candles, fetch_candles_for=_no_candles):
        long = _run(pricing.execution_price("SOL", "crypto", "long", now=now))
        short = _run(pricing.execution_price("SOL", "crypto", "short", now=now))
    assert long.price == 149.5 and short.price == 150.5, (long, short)
    assert long.source and long.timestamp and long.symbol and long.side
    assert short.source and short.timestamp and short.symbol and short.side
    assert len(calls) == 2, calls


def test_exit_quote_freshness_boundaries_are_explicit():
    pricing = load_module("app.brokers.execution_price")
    now = datetime(2026, 9, 18, 13, 0, tzinfo=timezone.utc)
    for age, valid in ((59, True), (61, False), (-1, True), (-3, False)):
        quote = _quote(ts=(now - timedelta(seconds=age)).isoformat())

        async def _read(symbol):
            return quote

        with _patched(data, get_crypto_quote=_read):
            result = _run(pricing.execution_price("SOL", "crypto", "long", now=now))
        assert (result is not None) is valid, (age, result)


def test_invalid_quotes_never_fall_back_to_historical_candles():
    pricing = load_module("app.brokers.execution_price")
    candles = load_module("app.data.candles")
    bad = [None, _quote(ts="not-a-time"),
           _quote(ts=_iso(days=4)), _quote(symbol="BTC/USD"),
           _quote(bid=0), _quote(ask=0), _quote(bid=-1),
           _quote(bid=True), _quote(ask=False),
           _quote(ts="2026-09-18T13:00:00"),
           _quote(bid=float("nan")), _quote(ask=float("inf")),
           _quote(bid=151, ask=150)]
    bad.append(_quote())
    bad[-1].ts = ""
    for quote in bad:
        async def _read(symbol):
            return quote

        with _patched(data, get_crypto_quote=_read), \
                _patched(candles, fetch_candles_for=_no_candles):
            result = _run(pricing.execution_price("SOL", "crypto", "long"))
        assert result is None, (quote, result)


def test_stock_exit_uses_stock_quote_and_rejects_unknown_asset():
    pricing = load_module("app.brokers.execution_price")
    calls = []

    async def _stock(symbol):
        calls.append(symbol)
        return _quote(symbol="AAPL", bid=201, ask=202)

    async def _unexpected(*_args, **_kwargs):
        raise AssertionError("wrong market-data source selected")

    with _patched(data, get_quote=_stock, get_crypto_quote=_unexpected):
        result = _run(pricing.execution_price("AAPL", "stock", "short"))
        unknown = _run(pricing.execution_price("AAPL", "mystery", "short"))
    assert result.price == 202 and calls == ["AAPL"], (result, calls)
    assert unknown is None, unknown


@contextlib.contextmanager
def _tick_harness(client, quote=None, held=None):
    """Use the real monitor; stub storage, quotes and unrelated side jobs."""
    events = []
    saved = (pm.PositionMonitorAgent._recon_tick_counter,
             pm.PositionMonitorAgent._did_initial_reconcile)
    pm.PositionMonitorAgent._recon_tick_counter = 0
    pm.PositionMonitorAgent._did_initial_reconcile = True

    async def _quote_read(symbol):
        return quote

    async def _held(book, **_kwargs):
        return {"SOLUSD"} if held is None else held

    async def _nostep(*_args, **_kwargs):
        return False, 0

    def _record(event, ticker="", **kwargs):
        events.append((event, ticker, kwargs))

    try:
        with _registry(), _patched(
                pm, _supabase=lambda: client,
                _latest_price=_no_candles,
                _manage_day_options=_noop, _gap_check_open_bell=_noop,
                _pre_break_review=_noop, check_and_lock_profit=_noop,
                _step_check=_nostep, close_position=_no_modeled_close,
                _arm_broker_stop=_noop, _push_crypto_tp=_noop,
                _maybe_ladder_stop=_noop, _maybe_trail_stock_profit=_noop,
                _maybe_trail_hodl=_noop,
                _crypto_reeval_enabled=lambda: False,
                _crypto_time_exit_enabled=lambda: False,
                _crypto_mae_adopted_enabled=lambda: False), \
                _patched(scope, held_symbols=_held), \
                _patched(data, get_crypto_quote=_quote_read), \
                _patched(engine, close_position=_no_modeled_close), \
                _patched(log, record=_record):
            yield events
    finally:
        (pm.PositionMonitorAgent._recon_tick_counter,
         pm.PositionMonitorAgent._did_initial_reconcile) = saved
        accounts.clear_account()


def test_stale_quote_cannot_trigger_a_broker_stop_or_modeled_close():
    row = _row()
    client = _Client([row])
    submitted = []

    async def _submit(*args, **kwargs):
        submitted.append((args, kwargs))
        return {"id": "should-not-submit", "status": "accepted"}, "ok"

    with _tick_harness(client, quote=_quote(
            bid=96.87, ask=96.90, ts=_iso(days=4))), \
            _patched(pm, _throttled_liquidate=_submit):
        out = _run(pm.PositionMonitorAgent().tick())
    assert submitted == [], submitted
    assert row["status"] == "open", row
    assert not [message for message in out if message.kind == "close"], out


def _order(order_id="sell-book-a", status="accepted", price=None, qty=0, **extra):
    order = {"id": order_id, "symbol": "SOLUSD", "side": "sell",
             "status": status, "filled_qty": str(qty),
             "filled_avg_price": str(price) if price is not None else None,
             "submitted_at": _iso(),
             "filled_at": _iso() if qty else None}
    order.update(extra)
    return order


@contextlib.contextmanager
def _helper_harness(*, order_reads=None, orders=None, allow_claim=True):
    helper = load_module("app.paper.broker_exit")
    claims, recorded, reads = [], [], []

    async def _claim(pos, expected, pending):
        claims.append((_bound_book(), expected, pending))
        payload = dict(pos.get("source_payload") or {})
        if not allow_claim or payload.get(helper.PENDING_KEY) != expected:
            return False
        if pending is None:
            payload.pop(helper.PENDING_KEY, None)
        else:
            payload[helper.PENDING_KEY] = dict(pending)
        pos["source_payload"] = payload
        return True

    async def _read_order(order_id):
        reads.append((_bound_book(), order_id))
        result = (order_reads or {}).get(order_id)
        return (result, None) if result is not None else (None, "unavailable")

    async def _read_orders(after):
        reads.append((_bound_book(), after))
        return orders

    async def _record(pos, order, reason):
        recorded.append((_bound_book(), pos["id"], dict(order), reason))
        price, qty = float(order["filled_avg_price"]), float(order["filled_qty"])
        remaining = max(0.0, float(pos["quantity"]) - qty)
        if not remaining:
            pos["status"] = "closed_stop"
        return engine.FillResult(ok=True, position_id=pos["id"], fill_price=price,
                                 realized_pnl_usd=qty * (price - pos["entry_price"]),
                                 remaining_qty=remaining)

    async def _verified_quantity(*_args, **_kwargs):
        return True

    with _patched(helper, _claim=_claim, _read_order=_read_order,
                  _read_closing_orders=_read_orders, _record=_record,
                  _verify_exit_quantity=_verified_quantity):
        yield helper, claims, recorded, reads


def test_submission_then_pending_poll_books_only_actual_fill_once():
    row = _row()
    client = _Client([row])
    submitted, receipts = [], {}

    async def _submit(symbol, asset_type="stock", user_id=None):
        submitted.append((symbol, asset_type, user_id, _bound_book()))
        return _order(), "ok"

    with _helper_harness(order_reads=receipts) as (_, claims, recorded, reads), \
            _tick_harness(client, quote=_quote(bid=139, ask=139.2)), \
            _patched(pm, _throttled_liquidate=_submit):
        agent = pm.PositionMonitorAgent()
        first = _run(agent.tick())
        assert row["status"] == "open" and recorded == [], (row, recorded)
        assert not [m for m in first if m.kind == "close"], first
        assert row["source_payload"]["broker_exit_pending"]["order_id"] == "sell-book-a"
        receipts["sell-book-a"] = _order()
        second = _run(agent.tick())
        assert len(submitted) == 1 and not recorded, (submitted, recorded)
        assert not [m for m in second if m.kind == "close"], second
        receipts["sell-book-a"] = _order(status="filled", price=138.75, qty=2)
        final = _run(agent.tick())
    assert submitted == [("SOL", "crypto", "book-a", "book-a")], submitted
    assert len(recorded) == 1 and recorded[0][2]["filled_avg_price"] == "138.75", recorded
    assert recorded[0][3] == "stop", recorded
    closes = [m for m in final if m.kind == "close"]
    assert len(closes) == 1 and closes[0].payload["exit_price"] == 138.75, final
    assert len(reads) == 2 and len(claims) == 2, (reads, claims)


def test_pending_exit_settles_without_a_quote_and_does_not_resubmit():
    row = _row(source_payload={"broker_exit_pending": {
        "intent_id": "intent", "started_at": _iso(minutes=2),
        "reason": "stop", "quantity": 2, "order_id": "sell-book-a"}})
    client = _Client([row])
    receipt = _order(status="filled", price=142.25, qty=2)

    async def _forbidden(*_args, **_kwargs):
        raise AssertionError("pending exit may not submit a second order")

    with _helper_harness(order_reads={"sell-book-a": receipt}) as (_, _, recorded, reads), \
            _tick_harness(client, quote=None), \
            _patched(pm, _throttled_liquidate=_forbidden):
        out = _run(pm.PositionMonitorAgent().tick())
    assert reads == [("book-a", "sell-book-a")] and len(recorded) == 1, (reads, recorded)
    assert [m.payload["exit_price"] for m in out if m.kind == "close"] == [142.25], out


def test_two_books_do_not_share_pending_orders_or_receipts():
    rows = [_row(book) for book in ("book-a", "book-b")]
    client, receipts, submitted = _Client(rows), {}, []

    async def _submit(symbol, asset_type="stock", user_id=None):
        submitted.append((user_id, _bound_book()))
        return _order(order_id="sell-" + user_id), "ok"

    with _helper_harness(order_reads=receipts) as (_, _, recorded, reads), \
            _tick_harness(client, quote=_quote(bid=139, ask=139.2)), \
            _patched(pm, _throttled_liquidate=_submit):
        agent = pm.PositionMonitorAgent()
        _run(agent.tick())
        receipts.update({
            "sell-book-a": _order(order_id="sell-book-a", status="filled", price=138, qty=2),
            "sell-book-b": _order(order_id="sell-book-b", status="filled", price=139, qty=2),
        })
        _run(agent.tick())
    assert submitted == [("book-a", "book-a"), ("book-b", "book-b")], submitted
    assert reads == [("book-a", "sell-book-a"), ("book-b", "sell-book-b")], reads
    assert [(book, order["id"], order["filled_avg_price"]) for book, _, order, _ in recorded] == [
        ("book-a", "sell-book-a", "138"), ("book-b", "sell-book-b", "139")], recorded


def test_unknown_submission_is_durable_and_never_blindly_retried():
    row, calls = _row(), []

    async def _submit():
        calls.append(_bound_book())
        raise TimeoutError("response lost after possible broker acceptance")

    with _registry(), _helper_harness() as (helper, _, recorded, _), \
            _patched(log, record=lambda *_a, **_k: None):
        first = _run(helper.settle_or_request_close(row, "stop", submit=_submit))
        second = _run(helper.settle_or_request_close(row, "stop", submit=_submit))
    assert not first.ok and first.pending and not second.ok and second.pending
    assert calls == ["book-a"] and recorded == [], (calls, recorded)
    assert row["source_payload"]["broker_exit_pending"]["order_id"] is None
    assert row["status"] == "open", row


def test_failed_durable_claim_blocks_broker_submission():
    row, calls = _row(), []

    async def _submit():
        calls.append(True)
        return _order(), "ok"

    with _registry(), _helper_harness(allow_claim=False) as (helper, _, _, _):
        result = _run(helper.settle_or_request_close(row, submit=_submit))
    assert not result.ok and calls == [], (result, calls)


def test_unavailable_pending_order_keeps_inventory_open():
    row = _row(source_payload={"broker_exit_pending": {
        "started_at": _iso(minutes=2), "order_id": "sell-book-a", "reason": "stop", "quantity": 2}})
    with _registry(), _helper_harness() as (helper, _, recorded, reads):
        result = _run(helper.settle_or_request_close(row))
    assert not result.ok and result.pending and recorded == [], (result, recorded)
    assert row["status"] == "open" and reads == [("book-a", "sell-book-a")]


def test_external_absence_requires_one_matching_filled_order():
    for orders, accepted in (
            (None, False), ([], False), ([_order()], False),
            ([_order(status="filled", price=142, qty=2, side="buy")], False),
            ([_order(status="filled", price=142, qty=2, submitted_at=_iso(days=2),
                     filled_at=_iso(days=2))], False),
            ([_order(status="filled", price=142, qty=2),
              _order(order_id="second-exit", status="filled", price=143, qty=2)], False),
            ([_order(status="filled", price=142, qty=2)], True)):
        row = _row()
        with _registry(), _helper_harness(orders=orders) as (helper, _, recorded, _):
            result = _run(helper.reconcile_broker_close(row))
        assert bool(result.ok) is accepted, (orders, result)
        assert bool(recorded) is accepted, (orders, recorded)
        if accepted:
            assert recorded[0][3] == "alpaca_external", recorded
        else:
            assert row["status"] == "open", row


def test_native_bracket_created_before_entry_matches_its_later_fill():
    row = _row(asset_type="stock", ticker="AAPL")
    receipt = _order(status="filled", price=142, qty=2, symbol="AAPL",
                     submitted_at=_iso(hours=2), filled_at=_iso(minutes=1))
    with _registry(), _helper_harness(orders=[receipt]) as (helper, _, recorded, _):
        result = _run(helper.reconcile_broker_close(row))
    assert result.ok and len(recorded) == 1, (result, recorded)


def test_absence_reconciliation_discovers_bracket_receipt_from_fill_activities():
    helper = load_module("app.paper.broker_exit")
    row = _row(asset_type="stock", ticker="AAPL")
    receipt = _order(order_id="native-bracket", status="filled", price=142,
                     qty=2, symbol="AAPL", submitted_at=_iso(hours=2),
                     filled_at=_iso(minutes=1))
    activities_seen, orders_seen, recorded = [], [], []

    async def _activities(after, *, activity_types):
        activities_seen.append((_bound_book(), after, activity_types))
        return [
            {"order_id": "native-bracket", "symbol": "AAPL", "side": "sell"},
            {"order_id": "native-bracket", "symbol": "AAPL", "side": "sell"},
            {"order_id": "entry", "symbol": "AAPL", "side": "buy"},
            {"order_id": "other-symbol", "symbol": "MSFT", "side": "sell"},
        ]

    async def _order_read(order_id):
        orders_seen.append((_bound_book(), order_id))
        return receipt, None

    async def _record(pos, order, reason):
        recorded.append((_bound_book(), pos["id"], order["id"], reason))
        return engine.FillResult(ok=True, fill_price=142)

    with _registry(), _patched(alp, get_fill_activities_strict=_activities), \
            _patched(helper, _read_order=_order_read, _record=_record):
        result = _run(helper.reconcile_broker_close(row))
    assert result.ok, result
    assert activities_seen == [("book-a", row["entry_at"], "FILL")], activities_seen
    assert orders_seen == [("book-a", "native-bracket")], orders_seen
    assert recorded == [("book-a", "sol-book-a", "native-bracket", "alpaca_external")], recorded


def test_pending_receipt_must_match_its_persisted_order_id():
    row = _row(source_payload={"broker_exit_pending": {
        "started_at": _iso(minutes=2), "order_id": "sell-book-a", "reason": "stop", "quantity": 2}})
    unrelated = _order(order_id="another-order", status="filled", price=142, qty=2)
    with _registry(), _helper_harness(order_reads={"sell-book-a": unrelated}) as (
            helper, _, recorded, _):
        result = _run(helper.settle_or_request_close(row))
    assert not result.ok and result.pending and recorded == [], (result, recorded)
    assert row["status"] == "open", row


def test_partial_receipt_emits_partial_information_and_keeps_position_open():
    row = _row(source_payload={"broker_exit_pending": {
        "intent_id": "intent", "started_at": _iso(minutes=2),
        "reason": "stop", "quantity": 2, "order_id": "sell-book-a"}})
    receipt = _order(status="partially_filled", price=142, qty=0.5)
    with _helper_harness(order_reads={"sell-book-a": receipt}) as (_, _, recorded, _), \
            _tick_harness(_Client([row]), quote=None):
        out = _run(pm.PositionMonitorAgent().tick())
    assert len(recorded) == 1 and row["status"] == "open", (recorded, row)
    assert not [m for m in out if m.kind == "close"], out
    partial = [m for m in out if m.payload.get("event") == "broker_partial_fill_confirmed"]
    assert len(partial) == 1 and partial[0].payload["remaining_qty"] == 1.5, out


def test_confirmed_unfilled_cancellation_releases_intent_without_closing():
    row = _row(source_payload={"broker_exit_pending": {
        "started_at": _iso(minutes=2), "order_id": "sell-book-a", "reason": "stop", "quantity": 2}})
    receipt = _order(status="canceled")
    with _registry(), _helper_harness(order_reads={"sell-book-a": receipt}) as (
            helper, _, recorded, _), _patched(log, record=lambda *_a, **_k: None):
        result = _run(helper.settle_or_request_close(row))
    assert not result.ok and recorded == [], (result, recorded)
    assert helper.PENDING_KEY not in row["source_payload"] and row["status"] == "open", row


def test_liquidation_requires_broker_inventory_to_match_the_row_and_request():
    helper = load_module("app.paper.broker_exit")
    cases = [
        ([{"symbol": "SOL/USD", "side": "long", "qty": "2"}], 2, True),
        ([{"symbol": "SOLUSD", "side": "long", "qty": "2.000000001"}], 2, True),
        (None, 2, False), ([], 2, False),
        ([{"symbol": "BTCUSD", "side": "long", "qty": "2"}], 2, False),
        ([{"symbol": "SOLUSD", "side": "short", "qty": "2"}], 2, False),
        ([{"symbol": "SOLUSD", "side": "long", "qty": "3"}], 2, False),
        ([{"symbol": "SOLUSD", "side": "long", "qty": "2"}], 1, False),
        ([{"symbol": "SOLUSD", "side": "long", "qty": "NaN"}], 2, False),
        ([{"symbol": "SOLUSD", "side": "long", "qty": "inf"}], 2, False),
        ([{"symbol": "SOLUSD", "side": "long", "qty": "0"}], 2, False),
        ([{"symbol": "SOLUSD", "side": "long", "qty": "2"},
          {"symbol": "SOL/USD", "side": "long", "qty": "2"}], 2, False),
    ]
    for positions, requested, valid in cases:
        seen = []

        async def _positions(*_args, **_kwargs):
            seen.append(_bound_book())
            return positions

        with _registry(), accounts.bind_for_user("book-a"), \
                _patched(alp, get_positions_strict=_positions):
            result = _run(helper._verify_exit_quantity(
                _row(), requested, full_liquidation=True))
        assert bool(result) is valid, (positions, requested, result)
        assert seen == ["book-a"], seen


def test_partial_exit_cannot_exceed_either_ledger_or_broker_inventory():
    helper = load_module("app.paper.broker_exit")
    for broker_qty, requested, valid in ((2, 0.5, True), (1, 0.5, True),
                                         (1, 1.5, False), (3, 2.5, False),
                                         (2, 0, False), (2, -1, False)):
        async def _positions(*_args, **_kwargs):
            return [{"symbol": "SOL/USD", "side": "long", "qty": str(broker_qty)}]

        with _registry(), accounts.bind_for_user("book-a"), \
                _patched(alp, get_positions_strict=_positions):
            result = _run(helper._verify_exit_quantity(
                _row(), requested, full_liquidation=False))
        assert bool(result) is valid, (broker_qty, requested, result)


def test_broker_inventory_read_exception_prevents_liquidation():
    helper = load_module("app.paper.broker_exit")

    async def _positions(*_args, **_kwargs):
        raise TimeoutError("strict holdings request failed")

    with _registry(), accounts.bind_for_user("book-a"), \
            _patched(alp, get_positions_strict=_positions):
        result = _run(helper._verify_exit_quantity(_row(), 2, full_liquidation=True))
    assert result is False, result


def test_account_verification_checks_identity_credentials_and_paper_endpoint():
    helper = load_module("app.paper.broker_exit")
    with _registry():
        account = accounts.account_for_user("book-a")
        other = accounts.account_for_user("book-b")
        for uid, yielded, headers, endpoint, venue, valid in (
                ("book-a", account, account.headers(), account.base_url, "paper", True),
                ("book-b", account, account.headers(), account.base_url, "paper", False),
                ("book-a", None, account.headers(), account.base_url, "paper", False),
                ("book-a", account, other.headers(), account.base_url, "paper", False),
                ("book-a", account, account.headers(), "https://api.alpaca.markets", "paper", False),
                ("book-a", account, account.headers(), account.base_url, "live", False)):
            with _patched(alp, _headers=lambda: headers, _base_url=lambda: endpoint,
                          broker_venue=lambda: venue):
                result = helper._bound_book_verified(uid, yielded)
            assert bool(result) is valid, (uid, endpoint, venue, result)


def test_secondary_book_cannot_submit_when_transport_falls_back_to_primary():
    submitted = []

    async def _submit():
        submitted.append(_bound_book())
        return _order(), "ok"

    with _registry(), _helper_harness() as (helper, claims, recorded, _):
        primary = accounts.account_for_user("book-a")
        secondary = accounts.account_for_user("book-b")
        # Simulate a degraded one-account registry that can still resolve a
        # stale secondary row while the transport only uses primary keys.
        with _patched(accounts, load_accounts=lambda: [primary],
                      multi_account_active=lambda: False,
                      should_skip_unresolved=lambda uid: False,
                      account_for_user=lambda uid: secondary if uid == "book-b" else primary), \
                _patched(route, multi_account_active=lambda: False), \
                _patched(alp, _account_ctx=lambda: None,
                         _headers=primary.headers, _base_url=lambda: primary.base_url,
                         broker_venue=lambda: "paper"):
            result = _run(helper.settle_or_request_close(_row("book-b"), submit=_submit))
    assert not result.ok and submitted == [] and claims == [] and recorded == [], result


def test_unknown_profit_step_count_never_becomes_a_zero_step_cache():
    goal = load_module("app.paper.daily_goal")

    async def _goal(*_args, **_kwargs):
        return {"hit": True}

    async def _unknown(*_args, **_kwargs):
        return None

    async def _failed(*_args, **_kwargs):
        raise TimeoutError("step history unavailable")

    with _patched(pm, _step_state={}), _patched(goal, goal_state=_goal):
        for reader in (_unknown, _failed):
            with _patched(engine, count_profit_steps=reader):
                result = _run(pm._step_check("position", "book-a", 10.0))
            assert result == (False, 0) and "position" not in pm._step_state, result


def test_profit_step_refresh_uses_persisted_count_without_double_increment():
    reads = []

    async def _count(user_id, position_id):
        reads.append((user_id, position_id))
        return 2

    with _patched(pm, _step_state={"position": {"n": 1, "ts": 0}}), \
            _patched(engine, count_profit_steps=_count):
        _run(pm._step_refresh("position", "book-a"))
        first = dict(pm._step_state["position"])
        _run(pm._step_refresh("position", "book-a"))
        second = dict(pm._step_state["position"])
    assert first["n"] == second["n"] == 2, (first, second)
    assert first["ts"] > 0 and second["ts"] >= first["ts"], (first, second)
    assert reads == [("book-a", "position"), ("book-a", "position")], reads


def test_pending_fill_cannot_exceed_the_claimed_exit_quantity():
    row = _row(source_payload={"broker_exit_pending": {
        "started_at": _iso(minutes=2), "order_id": "sell-book-a",
        "reason": "profit_step", "quantity": 1}})
    receipt = _order(status="filled", price=142, qty=2)
    with _registry(), _helper_harness(order_reads={"sell-book-a": receipt}) as (
            helper, _, recorded, _):
        result = _run(helper.settle_or_request_close(row))
    assert not result.ok and result.pending and "exceeds" in result.error, result
    assert recorded == [] and row["status"] == "open", (recorded, row)


def test_pending_fill_must_follow_its_intent_even_when_after_entry():
    row = _row(source_payload={"broker_exit_pending": {
        "started_at": _iso(minutes=2), "order_id": "sell-book-a",
        "reason": "stop", "quantity": 2}})
    receipt = _order(status="filled", price=142, qty=2,
                     submitted_at=_iso(minutes=4), filled_at=_iso(minutes=3))
    with _registry(), _helper_harness(order_reads={"sell-book-a": receipt}) as (
            helper, _, recorded, _):
        result = _run(helper.settle_or_request_close(row))
    assert not result.ok and result.pending and "mismatch" in result.error, result
    assert recorded == [] and row["status"] == "open", (recorded, row)


def test_profit_step_waits_for_terminal_receipt_and_recovers_on_duplicate():
    row = _row(source_payload={"broker_exit_pending": {
        "started_at": _iso(minutes=2), "order_id": "sell-book-a",
        "reason": "profit_step", "quantity": 1}})
    receipts = [
        engine.FillResult(ok=True, pending=True, duplicate=False,
                          fill_price=142, remaining_qty=1.5),
        engine.FillResult(ok=True, pending=False, duplicate=True,
                          fill_price=142, remaining_qty=1),
    ]
    settled, protected, refreshed = [], [], []

    async def _settle(pos, reason, **_kwargs):
        settled.append((pos["id"], reason, _bound_book()))
        return receipts[len(settled) - 1]

    async def _protect(pos, receipt):
        protected.append((pos["id"], receipt.remaining_qty, _bound_book()))
        return True

    async def _refresh(position_id, user_id):
        refreshed.append((position_id, user_id, _bound_book()))

    with _tick_harness(_Client([row]), quote=None), \
            _patched(pm, settle_or_request_close=_settle,
                     _reprotect_step_remainder=_protect, _step_refresh=_refresh):
        agent = pm.PositionMonitorAgent()
        first = _run(agent.tick())
        assert protected == [] and refreshed == [], (protected, refreshed)
        assert not [m for m in first if m.kind == "close"], first
        second = _run(agent.tick())
    assert settled == [("sol-book-a", "profit_step", "book-a")] * 2, settled
    assert protected == [("sol-book-a", 1, "book-a")], protected
    assert refreshed == [("sol-book-a", "book-a", "book-a")], refreshed
    assert not [m for m in second if m.kind == "close"], second


if __name__ == "__main__":
    raise SystemExit(run_tests(globals()))
