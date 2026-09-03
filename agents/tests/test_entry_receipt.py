"""Guards for the adoption clock (app/paper/entry_receipt.py).

THE ACCEPTANCE CASE IS REAL, and every number below is copied from the
broker's own records rather than invented.

Book acct2 (6ce61054), 2026-09-03. Order
6b0674af-bc72-4e8b-ae9c-e2bd2a2a6faa, side buy, XDTE, submitted 10:51:27Z
-- nearly three hours before the open -- and filled in FOUR pieces once
the bell rang:

    13:30:49.647776   13          @ 38.80
    13:33:24.270228    3          @ 38.82
    13:33:52.675383    2          @ 38.83
    13:33:52.676936    1.325521503 @ 38.83
                      -----------
                      19.325521503 @ 38.808267 average

The executor saw the order unfilled and wrote no row (the hole NOBL fell
through). The position sat unowned for 47 minutes. At 14:20:53.914599Z the
stock reconciler adopted it as ledger row
37d36b9e-123b-4692-baf2-ac71f24a11bc -- entry_price 38.808267, exactly
right, and entry_at == created_at == updated_at == 14:20:53.914599Z, which
is now() and nothing else. The QA inspector flagged qa_entry_time_drift
and correctly REFUSED to correct it, because moving entry_at moves an exit.

So the assertion these suites exist for is: entry_at must become
13:30:49.647776 -- the EARLIEST of the four -- and broker_order_id must be
carried onto the row instead of None.

The other half of the suite is the half that matters more. Most of these
tests assert that NOTHING was resolved: no order, several orders, a failed
fills read, a failed order read, a round trip in the window, a position
outside the lookback, a fill with no timestamp. HOUSE RULE 6 -- a wrong
entry_at is worse than a late one, because a late one only makes a
position look young while a wrong one silently moves an exit -- so every
one of those has to keep today's behaviour (the column defaults to now())
and say why in the row.

Dependency-free: no pytest, no .env, no network.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _bootstrap import (  # noqa: E402
    load_module, quiet_activity_log, run_tests, stub_config,
)

stub_config()
# app.runtime must be stubbed BEFORE position_monitor imports
# app.runtime.asset_policy, or the real package __init__ boots the bus and
# the scheduler -- same preamble, same order, as test_monitor_bookbound.
ap = load_module("app.runtime.asset_policy")
book_scope = load_module("app.runtime.book_scope")
rsettings = load_module("app.runtime.settings")
alp = load_module("app.brokers.alpaca")
accounts = load_module("app.brokers.accounts")
route_guard = load_module("app.brokers.route_guard")
alp_data = load_module("app.brokers.alpaca_data")
alog = load_module("app.agents.activity_log")
engine = load_module("app.paper.engine")
leg_sync = load_module("app.paper.leg_sync")
qa = load_module("app.paper.trade_qa")
er = load_module("app.paper.entry_receipt")
adoption = load_module("app.paper.adoption")
pm = load_module("app.agents.position_monitor")


# ---- the acceptance case, as the broker recorded it ----------------------

ACCT2 = "6ce61054-7ffd-41b5-80c3-1cd0220c79eb"
ACCT3 = "49acafdd-1c86-4740-a1b1-f94aa7abce08"
XDTE_ORDER = "6b0674af-bc72-4e8b-ae9c-e2bd2a2a6faa"
XDTE_FIRST_FILL = "2026-09-03T13:30:49.647776Z"
XDTE_ADOPTED_AT = "2026-09-03T14:20:53.914599Z"
XDTE_QTY = 19.325521503
XDTE_AVG = 38.808267

# now() for the deterministic tests: the microsecond the reconciler
# actually adopted the row.
NOW = datetime(2026, 9, 3, 14, 20, 53, 914599, tzinfo=timezone.utc)


def _xdte_position(qty: float = XDTE_QTY, avg: float = XDTE_AVG) -> dict:
    return {"symbol": "XDTE", "asset_class": "us_equity",
            "qty": str(qty), "avg_entry_price": str(avg),
            "current_price": "38.90"}


def _xdte_fills(order_id: str = XDTE_ORDER) -> list:
    """The four partials, in the order the activities endpoint returns
    them -- newest first, which is exactly why _entry_fill_at parses
    rather than takes the first row it sees."""
    raw = [
        ("2026-09-03T13:33:52.676936Z", 1.325521503, 38.83),
        ("2026-09-03T13:33:52.675383Z", 2, 38.83),
        ("2026-09-03T13:33:24.270228Z", 3, 38.82),
        ("2026-09-03T13:30:49.647776Z", 13, 38.80),
    ]
    return [{"id": f"f{i}", "activity_type": "FILL", "symbol": "XDTE",
             "side": "buy", "qty": str(q), "price": str(p),
             "transaction_time": ts, "order_id": order_id}
            for i, (ts, q, p) in enumerate(raw)]


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@contextlib.contextmanager
def _patched(mod, **attrs):
    """Swap module attributes and always put the originals back."""
    old = {k: (hasattr(mod, k), getattr(mod, k, None)) for k in attrs}
    try:
        for k, v in attrs.items():
            setattr(mod, k, v)
        yield
    finally:
        for k, (had, v) in old.items():
            if had:
                setattr(mod, k, v)
            elif hasattr(mod, k):
                delattr(mod, k)


@contextlib.contextmanager
def _env(**kw):
    old = {k: os.environ.get(k) for k in kw}
    try:
        for k, v in kw.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = str(v)
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@contextlib.contextmanager
def _bound(resolve=True, skip=False):
    """bind_for_user + should_skip_unresolved, without env slots."""
    @contextlib.contextmanager
    def _bind(uid):
        yield (object() if resolve else None)

    def _skip(uid):
        return skip
    with _patched(accounts, bind_for_user=_bind, should_skip_unresolved=_skip):
        yield


@contextlib.contextmanager
def _reads(fills=None, order=None, order_fn=None, calls=None):
    """The two broker seams entry_receipt has."""
    async def _f(after):
        if calls is not None:
            calls.append(("fills", after))
        return fills

    async def _one(oid):
        if calls is not None:
            calls.append(("order", oid))
        if order_fn is not None:
            return await order_fn(oid)
        return order if order is not None else (None, None)
    with _patched(er, _read_fills=_f, _read_order=_one):
        yield


def _load(uid=ACCT2):
    return _run(er.BookReceipts.load(uid))


# =========================================================================
# 1. THE XDTE ACCEPTANCE CASE
# =========================================================================


def test_xdte_four_partials_resolve_to_the_earliest_fill():
    """entry_at must become 13:30:49.647776, not 14:20:53."""
    with _bound(), _reads(fills=_xdte_fills()):
        book = _load()
        ev = _run(book.resolve(_xdte_position(), asset_type="stock", now=NOW))
    assert ev.settled, f"the receipt should settle this: {ev.why}"
    assert ev.entry_at == XDTE_FIRST_FILL, (
        f"entry_at {ev.entry_at!r}: the position was ENTERED at the first of "
        f"four partials, not the last and not now()")
    assert ev.entry_at != XDTE_ADOPTED_AT
    assert ev.source == "fills"
    assert ev.fills_used == 4, ev.fills_used


def test_xdte_carries_the_order_id_instead_of_none():
    """broker_order_id None was the other half of the defect."""
    with _bound(), _reads(fills=_xdte_fills()):
        ev = _run(_load().resolve(_xdte_position(), asset_type="stock",
                                  now=NOW))
    assert ev.broker_order_id == XDTE_ORDER, ev.broker_order_id


def test_xdte_backdate_is_the_real_fifty_minutes():
    """50.07 minutes: 13:30:49.647776 -> 14:20:53.914599. This number is
    what the exit-side shield keys on, so it has to be the truth."""
    with _bound(), _reads(fills=_xdte_fills()):
        ev = _run(_load().resolve(_xdte_position(), asset_type="stock",
                                  now=NOW))
    assert 50.0 < ev.backdated_min < 50.2, ev.backdated_min


def test_xdte_payload_names_the_receipt():
    with _bound(), _reads(fills=_xdte_fills()):
        ev = _run(_load().resolve(_xdte_position(), asset_type="stock",
                                  now=NOW))
    p = ev.payload()
    assert p["entry_at_source"] == "fills"
    assert p["entry_at_receipt_order_id"] == XDTE_ORDER
    assert p["entry_at_fills_used"] == 4
    assert "entry_at_unresolved" not in p


def test_xdte_price_still_reconciles_so_the_gate_is_really_running():
    """The gate is what makes the timestamp evidence rather than a
    coincidence: break the quantity and it must refuse."""
    with _bound(), _reads(fills=_xdte_fills()):
        ev = _run(_load().resolve(_xdte_position(qty=25.0),
                                  asset_type="stock", now=NOW))
    assert not ev.settled
    assert "fills sum to" in ev.why, ev.why


# =========================================================================
# 2. NO IDENTIFIABLE ORDER -> keep now(), never guess
# =========================================================================


def test_no_fill_in_window_keeps_the_adoption_clock():
    with _bound(), _reads(fills=[]):
        ev = _run(_load().resolve(_xdte_position(), asset_type="stock",
                                  now=NOW))
    assert not ev.settled and ev.entry_at is None
    assert "outside the lookback" in ev.why, ev.why
    p = ev.payload()
    assert p["entry_at_source"] == "adoption_clock"
    assert p["entry_at_read_failed"] is False


def test_two_orders_behind_one_position_is_refused_not_averaged():
    fills = _xdte_fills()
    fills[0] = {**fills[0], "order_id": "other-order-1111"}
    with _bound(), _reads(fills=fills):
        ev = _run(_load().resolve(_xdte_position(), asset_type="stock",
                                  now=NOW))
    assert not ev.settled
    assert "2 different orders" in ev.why, ev.why
    assert ev.broker_order_id is None


def test_fills_with_no_order_id_are_refused():
    fills = [{**f, "order_id": None} for f in _xdte_fills()]
    with _bound(), _reads(fills=fills):
        ev = _run(_load().resolve(_xdte_position(), asset_type="stock",
                                  now=NOW))
    assert not ev.settled
    assert "no order id" in ev.why, ev.why


def test_no_timestamp_anywhere_is_refused_not_invented():
    """Fills with no transaction_time and an order with no filled_at: the
    arithmetic closes, so it is tempting -- and it must still refuse."""
    fills = [{**f, "transaction_time": None, "date": None}
             for f in _xdte_fills()]
    order = ({"id": XDTE_ORDER, "status": "filled", "filled_at": None}, None)
    with _bound(), _reads(fills=fills, order=order):
        ev = _run(_load().resolve(_xdte_position(), asset_type="stock",
                                  now=NOW))
    assert not ev.settled
    assert "fill TIME" in ev.why, ev.why


def test_order_filled_at_is_the_documented_fallback():
    """No fill timestamp, but the ORDER carries one: that is still the
    venue's own record, so it is used and labelled as such."""
    fills = [{**f, "transaction_time": None, "date": None}
             for f in _xdte_fills()]
    order = ({"id": XDTE_ORDER, "status": "filled",
              "filled_at": "2026-09-03T13:33:52.676936Z"}, None)
    with _bound(), _reads(fills=fills, order=order):
        ev = _run(_load().resolve(_xdte_position(), asset_type="stock",
                                  now=NOW))
    assert ev.settled and ev.source == "order_filled_at"
    assert ev.entry_at == "2026-09-03T13:33:52.676936Z"


def test_a_future_fill_time_is_refused():
    """The OPEXP-dated-weeks-later shape, in the other direction."""
    fills = [{**f, "transaction_time": "2026-09-10T00:00:00Z"}
             for f in _xdte_fills()]
    with _bound(), _reads(fills=fills):
        ev = _run(_load().resolve(_xdte_position(), asset_type="stock",
                                  now=NOW))
    assert not ev.settled
    assert "in the\nfuture" in ev.why or "future" in ev.why, ev.why


def test_a_fill_before_the_window_start_is_refused():
    """THE BOUND. Everything downstream -- including the exit-side shield
    -- rests on a backdate never exceeding the lookback, so a timestamp
    the read cannot support is refused rather than trusted."""
    fills = [{**f, "transaction_time": "2026-01-01T00:00:00Z"}
             for f in _xdte_fills()]
    with _bound(), _reads(fills=fills):
        ev = _run(_load().resolve(_xdte_position(), asset_type="stock",
                                  now=NOW))
    assert not ev.settled
    assert "before the" in ev.why, ev.why


def test_backdate_never_exceeds_the_lookback():
    """Stated as an invariant over the real knob, not one example."""
    with _env(TREZO_QA_LOOKBACK_H="72"), _bound(), _reads(fills=_xdte_fills()):
        book = _load()
        ev = _run(book.resolve(_xdte_position(), asset_type="stock"))
    assert ev.settled
    assert ev.backdated_min <= 72 * 60.0 + 1, ev.backdated_min


# =========================================================================
# 3. RE-ADOPTION
# =========================================================================


def test_readoption_dates_from_the_fills_that_built_what_is_held_now():
    """A position closed and re-adopted keeps the age of the CURRENT
    broker position, not the moment of re-adoption. Here the four XDTE
    partials are still the only opening fills, and the row being written
    is the second one for the ticker: the honest entry is still 13:30:49.
    """
    with _bound(), _reads(fills=_xdte_fills()):
        ev = _run(_load().resolve(_xdte_position(), asset_type="stock",
                                  now=NOW))
    assert ev.settled and ev.entry_at == XDTE_FIRST_FILL


def test_readoption_with_the_previous_round_trip_in_the_window_refuses():
    """If the window also contains the SELL that closed the previous
    cycle, the fills in it did not all build what is held now -- so the
    gate refuses rather than dating the new position from the old one.
    This is the DOT close-and-re-adopt loop, refused."""
    fills = _xdte_fills() + [
        {"id": "sell1", "activity_type": "FILL", "symbol": "XDTE",
         "side": "sell", "qty": "5", "price": "38.5",
         "transaction_time": "2026-09-02T15:00:00Z",
         "order_id": "prior-cycle-close"}]
    with _bound(), _reads(fills=fills):
        ev = _run(_load().resolve(_xdte_position(), asset_type="stock",
                                  now=NOW))
    assert not ev.settled
    assert "round trip" in ev.why, ev.why


# =========================================================================
# 4. A FAILED READ AT EACH STEP -- house rule 3
# =========================================================================


def test_failed_fills_read_is_not_an_empty_window():
    with _bound(), _reads(fills=None):
        book = _load()
        ev = _run(book.resolve(_xdte_position(), asset_type="stock", now=NOW))
    assert book.read_failed
    assert not ev.settled
    assert ev.read_failed is True
    assert ev.payload()["entry_at_read_failed"] is True


def test_failed_order_read_is_answerless_not_absent():
    fills = [{**f, "transaction_time": None, "date": None}
             for f in _xdte_fills()]
    with _bound(), _reads(fills=fills, order=(None, "429 rate limited")):
        ev = _run(_load().resolve(_xdte_position(), asset_type="stock",
                                  now=NOW))
    assert not ev.settled and ev.read_failed is True
    assert "429" in ev.why, ev.why


def test_order_that_does_not_exist_is_an_answer_not_a_failure():
    fills = [{**f, "transaction_time": None, "date": None}
             for f in _xdte_fills()]
    with _bound(), _reads(fills=fills, order=(None, None)):
        ev = _run(_load().resolve(_xdte_position(), asset_type="stock",
                                  now=NOW))
    assert not ev.settled and ev.read_failed is False
    assert "no such order" in ev.why, ev.why


def test_a_raising_broker_read_does_not_take_the_adoption_down():
    async def _boom(after):
        raise RuntimeError("socket hung up")
    with _bound(), _patched(er, _read_fills=_boom):
        book = _load()
    assert book.read_failed and "socket hung up" in book.error


def test_a_raising_resolve_is_caught_and_unsettled():
    def _explode(*a, **k):
        raise ValueError("gate blew up")
    with _bound(), _reads(fills=_xdte_fills()), _patched(qa, _arith_gate=_explode):
        ev = _run(_load().resolve(_xdte_position(), asset_type="stock",
                                  now=NOW))
    assert not ev.settled
    assert "ValueError" in ev.why, ev.why


def test_unresolvable_book_reads_nothing_at_all():
    """HOUSE RULE 2. Reading another book's fills is how a stranger's
    timestamp lands in this ledger."""
    calls = []
    with _bound(resolve=False, skip=True), _reads(fills=_xdte_fills(),
                                                  calls=calls):
        book = _load("book-that-does-not-exist")
        ev = _run(book.resolve(_xdte_position(), asset_type="stock", now=NOW))
    assert calls == [], calls
    assert book.read_failed and not ev.settled


# =========================================================================
# 5. PER-BOOK KEYING AND BOUNDED CALLS
# =========================================================================


def test_one_fills_read_per_book_not_per_position():
    calls = []
    with _bound(), _reads(fills=_xdte_fills(), calls=calls):
        book = _load()
        for _ in range(5):
            _run(book.resolve(_xdte_position(), asset_type="stock", now=NOW))
    assert [c for c in calls if c[0] == "fills"] == [calls[0]], calls


def test_each_book_binds_and_reads_for_itself():
    seen = []

    @contextlib.contextmanager
    def _bind(uid):
        seen.append(uid)
        yield object()

    def _skip(uid):
        return False
    with _patched(accounts, bind_for_user=_bind, should_skip_unresolved=_skip), \
            _reads(fills=_xdte_fills()):
        _load(ACCT2)
        _load(ACCT3)
    assert seen == [ACCT2, ACCT3], seen


def test_order_dereference_budget_is_bounded():
    fills = [{**f, "transaction_time": None, "date": None}
             for f in _xdte_fills()]
    calls = []
    with _bound(), _reads(fills=fills, order=(None, None), calls=calls):
        book = _load()
        for _ in range(20):
            _run(book.resolve(_xdte_position(), asset_type="stock", now=NOW))
    assert len([c for c in calls if c[0] == "order"]) == er._MAX_ORDER_READS


def test_crypto_symbol_is_normalised_to_the_ledger_spelling():
    """'BTC/USD' at the broker is 'BTC' in the ledger; without the shared
    normaliser the fills would never be found for a coin."""
    fills = [{"id": "c1", "activity_type": "FILL", "symbol": "BTC/USD",
              "side": "buy", "qty": "0.5", "price": "79000",
              "transaction_time": "2026-09-03T12:00:00Z",
              "order_id": "coin-order-1"}]
    pos = {"symbol": "BTCUSD", "asset_class": "crypto", "qty": "0.5",
           "avg_entry_price": "79000"}
    with _bound(), _reads(fills=fills):
        ev = _run(_load().resolve(pos, asset_type="crypto", now=NOW))
    assert ev.settled, ev.why
    assert ev.entry_at == "2026-09-03T12:00:00Z"


# =========================================================================
# 6. THE CONVENTION AGREES WITH THE QA INSPECTOR'S
# =========================================================================


def test_entry_convention_is_literally_trade_qas():
    """Not "matches" -- IS. One function object, so the two cannot drift."""
    assert er._qa is qa
    fills = _xdte_fills()
    mine = _run(_load_for_convention(fills))
    theirs = qa._entry_fill_at(
        [f for f in fills if str(f.get("side")).startswith("buy")],
        XDTE_ORDER)
    assert mine == theirs == XDTE_FIRST_FILL, (mine, theirs)


async def _load_for_convention(fills):
    with _bound(), _reads(fills=fills):
        book = await er.BookReceipts.load(ACCT2)
        ev = await book.resolve(_xdte_position(), asset_type="stock", now=NOW)
    return ev.entry_at


def test_the_inspector_would_report_zero_drift_on_a_row_we_wrote():
    """qa_entry_time_drift compares entry_at to the earliest fill in the
    SAME window. A row this module dated must therefore drift by zero --
    otherwise the inspector flags rows the adopter just got right."""
    fills = _xdte_fills()
    with _bound(), _reads(fills=fills):
        ev = _run(_load().resolve(_xdte_position(), asset_type="stock",
                                  now=NOW))
    best = None
    for f in fills:
        ts = qa._parse_ts(f.get("transaction_time") or f.get("date"))
        if ts and (best is None or ts < best):
            best = ts
    drift = abs((qa._parse_ts(ev.entry_at) - best).total_seconds()) / 60.0
    assert drift == 0.0, drift


def test_same_lookback_knob_as_the_inspector():
    calls = []
    with _env(TREZO_QA_LOOKBACK_H="12"), _bound(), _reads(fills=[], calls=calls):
        _load()
    after = calls[0][1]
    assert after == qa._after_iso(12.0)[:len(after)] or after.endswith("Z"), after
    parsed = qa._parse_ts(after)
    hours = (datetime.now(timezone.utc) - parsed).total_seconds() / 3600.0
    assert 11.9 < hours < 12.2, hours


# =========================================================================
# 7. THE ENGINE WRITES IT, AND ONLY WHEN IT IS GIVEN ONE
# =========================================================================


def _engine_insert(entry_at):
    """Drive engine.record_external_position against a fake client and
    return the row it tried to insert."""
    engine = load_module("app.paper.engine")
    captured = {}

    class _Tbl:
        def __init__(self, name):
            self.name = name
            self.op = None
            self.payload = None

        def select(self, *a, **k):
            self.op = "select"
            return self

        def insert(self, row):
            self.op, self.payload = "insert", row
            return self

        def eq(self, *a):
            return self

        def neq(self, *a):
            return self

        def order(self, *a, **k):
            return self

        def limit(self, n):
            return self

        def execute(self):
            if self.op == "insert":
                captured["row"] = dict(self.payload)
                return type("R", (), {"data": [{"id": "new-row"}]})()
            return type("R", (), {"data": []})()

    class _C:
        def table(self, name):
            return _Tbl(name)

    with _patched(engine, _supabase=lambda: _C()):
        res = _run(engine.record_external_position(
            user_id=ACCT2, ticker="XDTE", asset_type="stock", side="long",
            quantity=XDTE_QTY, entry_price=XDTE_AVG, stop_price=37.0,
            target_price=41.0, strategy="reconciled", broker="alpaca",
            broker_order_id=XDTE_ORDER,
            source_payload={"auto_reconcile": True},
            entry_at=entry_at))
    assert res.ok, res.error
    return captured["row"]


def test_engine_writes_the_receipt_time_when_given_one():
    with quiet_activity_log():
        row = _engine_insert(XDTE_FIRST_FILL)
    assert row["entry_at"] == XDTE_FIRST_FILL
    assert row["broker_order_id"] == XDTE_ORDER


def test_engine_omits_entry_at_entirely_when_it_has_none():
    """Omitted, not NULL: sending None would override the column default
    and every age calculation reads an unparseable entry_at as 0 days."""
    with quiet_activity_log():
        row = _engine_insert(None)
    assert "entry_at" not in row, row.get("entry_at")


# =========================================================================
# 8. THE EXIT-SIDE SHIELD (position_monitor), driven for real
# =========================================================================
#
# THE CASE, from book 49acafdd's own records. XLP, 120 shares short,
# adopted 2026-09-02 12:22:54 -- and adoption inherited the strategy tag
# "scalp" from the row that had just been closed. Its opening fill (order
# 546760a2) was 2026-09-01 16:37:43, 1185.2 minutes earlier. Give that row
# an honest clock and it is thirteen times past max_hold_90min the instant
# it exists, so the very next tick market-sells 120 shares -- an exit
# nobody asked for, caused by the act of adopting. adoption.py's contract
# is explicit that this must not happen, so the exit is shielded for
# exactly as long as the backdate is what is triggering it.

XLP_BACKDATE_MIN = 1185.2


def _scalp_row(*, backdated: float, managed_min: float) -> dict:
    """The XLP shape: a scalp-tagged adopted row whose entry_at sits
    `backdated` minutes before the moment the row was created, and which
    has now existed for `managed_min` minutes."""
    entry = (datetime.now(timezone.utc)
             - timedelta(minutes=backdated + managed_min))
    sp = {"adopted": True}
    if backdated:
        sp["entry_at_backdated_min"] = backdated
    return {"strategy": "scalp", "side": "short", "entry_price": 85.42,
            "entry_at": entry.isoformat(), "source_payload": sp}


def test_todays_behaviour_reproduced_a_fresh_row_never_times_out():
    """The defect, stated as a test: with entry_at = now() the 90-minute
    cap can never fire on an adopted scalp, however old it really is."""
    assert pm._decide_time_stop(
        _scalp_row(backdated=0, managed_min=2), "short", 85.0, 86.0) == (None, "")


def test_backdated_row_is_not_market_sold_on_its_first_tick():
    reason, detail = pm._decide_time_stop(
        _scalp_row(backdated=XLP_BACKDATE_MIN, managed_min=2),
        "short", 85.0, 86.0)
    assert reason is None, (reason, detail)
    assert "adopted_backdated" in detail
    assert "TREZO_ADOPTED_TIME_EXIT=1" in detail


def test_the_shield_expires_by_itself():
    """Once the ROW has genuinely been managed for the threshold the rule
    fires normally -- the shield can never become a permanent exemption."""
    reason, detail = pm._decide_time_stop(
        _scalp_row(backdated=XLP_BACKDATE_MIN, managed_min=200),
        "short", 85.0, 86.0)
    assert (reason, detail) == ("time", "max_hold_90min")


def test_the_switch_defaults_to_the_safe_side_and_can_be_turned_off():
    row = _scalp_row(backdated=XLP_BACKDATE_MIN, managed_min=2)
    assert os.environ.get("TREZO_ADOPTED_TIME_EXIT") in (None, "", "0"), (
        "the shipped default must be the safe side")
    with _env(TREZO_ADOPTED_TIME_EXIT="1"):
        assert pm._decide_time_stop(row, "short", 85.0, 86.0) == (
            "time", "max_hold_90min")


def test_pre_existing_rows_are_untouched_by_the_shield():
    """No entry_at_backdated_min in the payload -> backdate 0 -> shield
    False. Nothing written before 2026-09-03 changes behaviour."""
    old = {"strategy": "scalp", "side": "short", "entry_price": 85.42,
           "entry_at": (datetime.now(timezone.utc)
                        - timedelta(minutes=400)).isoformat(),
           "source_payload": {"adopted": True}}
    assert pm._backdate_min(old) == 0.0
    assert pm._decide_time_stop(old, "short", 85.0, 86.0) == (
        "time", "max_hold_90min")


def test_the_345_force_exit_is_a_calendar_rule_and_is_not_shielded():
    """"The session is ending" is true of a backdated row too, so that
    branch must stay unshielded."""
    src = (Path(__file__).resolve().parents[1]
           / "app/agents/position_monitor.py").read_text(encoding="utf-8")
    i = src.index('return "eod", "force_exit_345pm"')
    assert "_backdate_shields_time_exit" not in src[i - 400:i]


def test_stagnation_rule_is_shielded_on_the_same_terms():
    row = _scalp_row(backdated=XLP_BACKDATE_MIN, managed_min=2)
    # 80 minutes managed would trip stagnation but not max hold; here the
    # backdate trips both, so the earlier shield answers first.
    reason, detail = pm._decide_time_stop(row, "short", 85.0, 86.0)
    assert reason is None
    src = (Path(__file__).resolve().parents[1]
           / "app/agents/position_monitor.py").read_text(encoding="utf-8")
    assert "_backdate_shields_time_exit(r, held, STAGNATION_MINUTES)" in src


def test_crypto_losing_time_limit_is_shielded_too():
    """TREZO_CRYPTO_TIME_EXIT is off by default, so this only bites when
    Mike turns it on -- and then a backdated coin must not be sold by the
    act of adopting it either."""
    coin = {"asset_type": "crypto", "side": "long", "strategy": "crypto_scalp",
            "entry_price": 100.0,
            "entry_at": (datetime.now(timezone.utc)
                         - timedelta(minutes=1441 + 2)).isoformat(),
            "source_payload": {"adopted": True,
                               "entry_at_backdated_min": 1441.0}}
    with _env(TREZO_CRYPTO_TIME_EXIT="1"):
        reason, detail = pm._decide_crypto_stale_exit(coin, 99.0)
        assert reason is None, (reason, detail)
        assert "adopted_backdated" in detail
        # and it still fires once the row itself is old enough
        coin_managed = dict(coin)
        coin_managed["entry_at"] = (
            datetime.now(timezone.utc)
            - timedelta(minutes=1441 + 1500)).isoformat()
        reason2, _ = pm._decide_crypto_stale_exit(coin_managed, 99.0)
        assert reason2 == "time", reason2


def test_crypto_shield_does_not_swallow_the_underwater_line():
    """The MAE 'seen, not acted on' line must survive the shield's own
    detail -- it is the only thing that says a coin is under the ceiling.
    """
    coin = {"asset_type": "crypto", "side": "long", "strategy": "crypto_swing",
            "entry_price": 100.0,
            "entry_at": (datetime.now(timezone.utc)
                         - timedelta(minutes=5761 + 2)).isoformat(),
            "source_payload": {"adopted": True,
                               "entry_at_backdated_min": 5761.0}}
    with _env(TREZO_CRYPTO_TIME_EXIT="1", TREZO_CRYPTO_MAE_ADOPTED=None):
        reason, detail = pm._decide_crypto_stale_exit(coin, 85.0)
    assert reason is None
    assert "adopted_underwater" in detail and "adopted_backdated" in detail


# =========================================================================
# 9. THE TWO CREATE PATHS ACTUALLY CALL IT (house rule 4: reached)
# =========================================================================


def _src(rel):
    return (Path(__file__).resolve().parents[1] / rel).read_text(
        encoding="utf-8", errors="replace")


def test_stocks_reconcile_resolves_before_it_inserts():
    t = _src("app/paper/stocks_reconcile.py")
    assert "from app.paper.entry_receipt import BookReceipts" in t
    assert '_receipts.resolve(ap, asset_type="stock")' in t
    assert "broker_order_id=_ev.broker_order_id," in t
    assert "entry_at=_ev.entry_at," in t
    assert "**_ev.payload()," in t


def test_adoption_resolves_before_it_inserts():
    t = _src("app/paper/adoption.py")
    assert "from app.paper.entry_receipt import BookReceipts" in t
    assert "receipts.resolve(bp, asset_type=at)" in t
    assert "broker_order_id=ev.broker_order_id," in t
    assert "entry_at=ev.entry_at)" in t


def test_both_paths_fail_soft_if_the_resolver_is_missing():
    """An unmanaged position is worse than a young-looking one: a build
    without entry_receipt must still adopt, and must record which clock
    the row got."""
    for rel in ("app/paper/stocks_reconcile.py", "app/paper/adoption.py"):
        t = _src(rel)
        assert "_UNLOADED" in t and "def _no_receipt(" in t, rel
        assert '"entry_at_source": "adoption_clock"' in t, rel


def test_both_paths_say_what_they_did():
    for rel in ("app/paper/stocks_reconcile.py", "app/paper/adoption.py"):
        assert "entry_receipt import announce" in _src(rel), rel


def test_announce_says_both_outcomes():
    with quiet_activity_log() as said:
        er.announce(er.EntryEvidence(entry_at=XDTE_FIRST_FILL,
                                     broker_order_id=XDTE_ORDER,
                                     source="fills", backdated_min=50.1,
                                     fills_used=4),
                    user_id=ACCT2, ticker="XDTE", asset_type="stock")
        er.announce(er._unsettled("no fill in the window"),
                    user_id=ACCT2, ticker="XDTE", asset_type="stock")
    events = [e for e, _t, _k in said]
    assert events == ["entry_at_from_receipt", "entry_at_unresolved"], events
    assert XDTE_ORDER in said[0][2]["reason"]
    assert "no fill in the window" in said[1][2]["reason"]



# --- REVIEW 2026-09-03: three blocking defects, pinned ---------------------

def test_a_date_only_activity_is_never_stamped_as_midnight():
    """_entry_fill_at falls back to an activity's `date` when there is no
    transaction_time. A date has no clock, so storing it means MIDNIGHT --
    up to 24h earlier than the real fill, on the column that moves exits,
    and inside the window so the bound cannot catch it."""
    assert er._has_time_of_day("2026-09-03T13:30:49.647776Z") is True
    assert er._has_time_of_day("2026-09-03 13:30:49") is True
    assert er._has_time_of_day("2026-09-03") is False
    assert er._has_time_of_day("") is False
    assert er._has_time_of_day(None) is False


def test_an_unparseable_window_start_refuses_rather_than_skips_the_bound():
    """The module says the bound is asserted. With no parseable window
    start it used to be skipped, so half the assertion did not exist."""
    import inspect
    src = inspect.getsource(er)
    assert "if self.window_start is None:" in src, (
        "the None case must refuse, not fall through to the comparison")
    i_none = src.index("if self.window_start is None:")
    i_cmp = src.index("if dt < self.window_start:")
    assert i_none < i_cmp, "the refusal must precede the comparison"


def test_the_fresh_row_grace_is_measured_on_managed_time_not_trade_time():
    """position_monitor's 5-minute reconcile-close grace measured
    entry_at, which is now the TRADE's age. A backdated adopted row would
    arrive with the grace already spent -- zero protection on its first
    tick, on exactly the rows this change backdates. That is the DOT
    close-and-re-adopt loop, made faster by the fix meant to end it."""
    import inspect
    pm = load_module("app.agents.position_monitor")
    src = inspect.getsource(pm)
    guard = "_backdate_shields_time_exit(r, _held_min_g, 5.0)"
    assert guard in src, "the reconcile-close grace must shield a backdated row"
    # and it must guard the reconcile-close skip, not sit somewhere inert
    after = src[src.index(guard):src.index(guard) + 400]
    assert "alpaca_managed += 1" in after and "continue" in after, after[:200]

if __name__ == "__main__":
    raise SystemExit(run_tests(globals()))
