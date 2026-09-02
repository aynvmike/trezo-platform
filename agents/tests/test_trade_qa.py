"""Guards for the trade QA inspector (app/paper/trade_qa.py).

THE CASE THESE REPLAY IS REAL. Order edefd889-bc5c-4cf3-9c0a-03eee25e0162
on book acct3 (49acafdd, the 75k): SELL 1 NOBL260918P00055000, a
cash-secured put, submitted 17:07:11Z on 2026-09-02, NOT filled when the
executor looked, filled 18:25:20Z -- seventy-eight minutes later -- 1
contract at 0.05. `paper_positions` held zero NOBL rows in any status on
any book. The broker had the short put; the ledger did not know it
existed, so it had no stop, no target, no ladder and no owner.

What these suites are really guarding is the DIFFERENCE between this
component and the reconcilers that came before it. Those compared
position snapshots and guessed, and the guessing is what produced the
close-and-re-adopt loops and the invented geometry. So the assertions
here are mostly assertions that NOTHING WAS WRITTEN: a failed read writes
nothing, a truncated window writes nothing, two candidate receipts write
nothing, an arithmetic disagreement writes nothing, a multi-leg order
writes nothing. A reconciler that is confidently wrong is worse than one
that says "I don't know", and these are the tests that keep it saying so.

Deliberately dependency-free (no pytest, no .env, no network) so the
deploy gate can run them in a bare checkout.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _bootstrap import (  # noqa: E402
    load_module, quiet_activity_log, run_tests, stub_config,
)

stub_config()
alp = load_module("app.brokers.alpaca")
accounts = load_module("app.brokers.accounts")
route_guard = load_module("app.brokers.route_guard")
adoption = load_module("app.paper.adoption")
qa = load_module("app.paper.trade_qa")

AGENTS = Path(__file__).resolve().parents[1]

# ---- the acceptance case, as the broker recorded it ---------------------
ACCT3 = "49acafdd-1c86-4740-a1b1-f94aa7abce08"
ACCT2 = "6ce61054-7ffd-41b5-80c3-1cd0220c79eb"
NOBL = "NOBL260918P00055000"
NOBL_ORDER = "edefd889-bc5c-4cf3-9c0a-03eee25e0162"
SUBMITTED = "2026-09-02T17:07:11Z"
FILLED = "2026-09-02T18:25:20Z"


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@contextlib.contextmanager
def _patched(mod, **attrs):
    """Swap module attributes and always put the originals back. A
    staticmethod would need staticmethod() to restore; none here are."""
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


_UNSET = object()


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


# ---- a Supabase stand-in that remembers every write ---------------------


class _Resp:
    def __init__(self, data):
        self.data = data


class _Tbl:
    def __init__(self, name, client):
        self.name, self.c = name, client
        self.eqs, self.op, self.payload = {}, None, None

    def select(self, *a, **k):
        self.op = "select"
        return self

    def insert(self, row):
        self.op, self.payload = "insert", row
        return self

    def update(self, patch):
        self.op, self.payload = "update", patch
        return self

    def eq(self, k, v):
        self.eqs[k] = v
        return self

    def limit(self, n):
        return self

    def execute(self):
        if self.op == "insert":
            self.c.writes.append((self.name, "insert", self.payload))
            self.c.rows.setdefault(self.name, []).append(dict(self.payload))
            return _Resp([self.payload])
        if self.op == "update":
            self.c.writes.append((self.name, "update", self.payload,
                                  dict(self.eqs)))
            return _Resp([])
        rows = self.c.rows.get(self.name, [])
        return _Resp([r for r in rows
                      if all(str(r.get(k)) == str(v)
                             for k, v in self.eqs.items())])


class FakeClient:
    def __init__(self, **tables):
        self.rows = {k: [dict(r) for r in v] for k, v in tables.items()}
        self.writes = []

    def table(self, name):
        return _Tbl(name, self)


def _ledger_writes(c):
    """Only writes that touch the money-shaped table. ops_health_alerts
    inserts are tickets, not ledger changes."""
    return [w for w in c.writes if w[0] == "paper_positions"]


@contextlib.contextmanager
def _bound(ok=True, resolve=True):
    """Stand in for bind_for_user + check_route without env slots."""
    @contextlib.contextmanager
    def _bind(uid):
        yield (object() if resolve else None)

    def _route(uid):
        return (True, "ok:test") if ok else (False, f"bound NONE but book {uid[:8]}")
    with _patched(accounts, bind_for_user=_bind), \
            _patched(route_guard, check_route=_route):
        yield


@contextlib.contextmanager
def _reads(positions=None, orders=None, fills=None, order=None,
           order_fn=None, open_orders=_UNSET):
    """Every broker seam the module has, patched together.

    `open_orders` (the live status=open read behind the SHIELD and I5)
    defaults to whatever `orders` was given, so the suites written before
    it existed keep meaning what they meant. Pass it explicitly -- None
    included -- to say something different about the live read than about
    the historical window.
    """
    _open = orders if open_orders is _UNSET else open_orders

    async def _p(uid):
        return positions

    async def _o(after):
        return orders

    async def _oo():
        return _open

    async def _f(after):
        return fills

    async def _one(oid):
        if order_fn is not None:
            return await order_fn(oid)
        return order if order is not None else (None, None)
    with _patched(qa, _read_positions=_p, _read_orders=_o, _read_fills=_f,
                  _read_order=_one, _read_open_orders=_oo):
        yield


@contextlib.contextmanager
def _quiet_alerts():
    sent = []

    async def _n(title, body, *, severity, key, fields=None):
        sent.append((key, severity, title))
    with _patched(qa, _notify=_n):
        yield sent


# ---- fixtures -----------------------------------------------------------


def nobl_position(qty="-1", avg="0.05"):
    return {"symbol": NOBL, "asset_class": "us_option", "qty": qty,
            "avg_entry_price": avg, "market_value": "-30"}


def nobl_order(status="filled", **over):
    o = {"id": NOBL_ORDER, "symbol": NOBL, "side": "sell", "qty": "1",
         "filled_qty": "1", "type": "market", "status": status,
         "submitted_at": SUBMITTED, "filled_at": FILLED,
         "filled_avg_price": "0.05", "order_class": "simple", "legs": [],
         "asset_class": "us_option"}
    o.update(over)
    return o


def nobl_fill(**over):
    f = {"id": "act-1", "activity_type": "FILL", "transaction_time": FILLED,
         "type": "fill", "price": "0.05", "qty": "1", "side": "sell_short",
         "symbol": NOBL, "order_id": NOBL_ORDER}
    f.update(over)
    return f


def _sweep(client, uid=ACCT3, **reads):
    with _bound(), _quiet_alerts() as sent, _reads(**reads), \
            quiet_activity_log() as said:
        rep = _run(qa.qa_sweep_for_book(client, uid))
    return rep, [e for e, _t, _k in said], sent


# =========================================================================
# THE ACCEPTANCE CASE
# =========================================================================


def test_nobl_replay_detects_the_orphan_and_logs_a_row_mike_can_read():
    """The inspector must SEE it. Everything else is a policy question."""
    qa.reset_state()
    c = FakeClient(paper_positions=[])
    with _env(TREZO_QA_AUTOFIX="0"):
        rep, events, _ = _sweep(c, positions=[nobl_position()],
                                orders=[nobl_order()], fills=[nobl_fill()])
    assert rep["skipped_reason"] is None, rep
    assert "qa_sweep" in events, events
    assert "qa_receipt_linked" in events, events
    assert "qa_would_fix" in events, events
    assert not _ledger_writes(c), c.writes


def test_nobl_replay_autofix_off_writes_nothing_and_says_what_it_would_do():
    """OFF is the shipped default and it is not a 'posture'."""
    qa.reset_state()
    c = FakeClient(paper_positions=[])
    with _env(TREZO_QA_AUTOFIX="0"):
        rep, events, _ = _sweep(c, positions=[nobl_position()],
                                orders=[nobl_order()], fills=[nobl_fill()])
    assert rep["booked"] == 0, rep
    assert not _ledger_writes(c), c.writes
    wf = [w for w in rep["would_fix"] if w["action"] == "A1_create"]
    assert len(wf) == 1, rep["would_fix"]
    p = wf[0]["payload"]
    assert p["ticker"] == NOBL and p["quantity"] == 1.0, p
    assert p["entry_price"] == 0.05 and p["entry_at"] == FILLED, p


def test_nobl_replay_books_one_row_with_the_fill_time_and_no_geometry():
    """The ONE write a receipt settles beyond doubt.

    Asserted on the INSERT PAYLOAD, not on the outcome: stop_price and
    target_price must be ABSENT, not null and not zero. A row that carries
    a fabricated stop is the DOT -13.6% bug, and 'the outcome looked fine'
    is how it shipped last time.
    """
    qa.reset_state()
    c = FakeClient(paper_positions=[])
    with _env(TREZO_QA_AUTOFIX="1", TREZO_ADOPT_ORPHANS="0"):
        rep, events, _ = _sweep(c, positions=[nobl_position()],
                                orders=[nobl_order()], fills=[nobl_fill()])
    w = _ledger_writes(c)
    assert len(w) == 1 and w[0][1] == "insert", c.writes
    p = w[0][2]
    assert "stop_price" not in p, p
    assert "target_price" not in p, p
    assert p["user_id"] == ACCT3 and p["ticker"] == NOBL, p
    assert p["side"] == "short" and p["quantity"] == 1.0, p
    assert p["entry_price"] == 0.05, p
    assert p["entry_at"] == FILLED, "entry_at must be the FILL time"
    assert p["status"] == "open", p
    assert p["broker_order_id"] == NOBL_ORDER, p
    assert p["strategy"] == "qa_unassigned", p
    assert p["source_payload"]["qa"]["state"] == "quarantined", p
    assert rep["booked"] == 1 and rep["quarantined"] >= 1, rep
    assert "qa_booked" in events, events
    assert "qa_quarantine" in events, events


def test_replaying_the_same_sweep_twice_creates_nothing_new():
    """Idempotence comes from the EXISTING broker_order_id column, not from
    a cursor or a watermark: a restart re-derives the identical window."""
    qa.reset_state()
    c = FakeClient(paper_positions=[])
    reads = dict(positions=[nobl_position()], orders=[nobl_order()],
                 fills=[nobl_fill()])
    with _env(TREZO_QA_AUTOFIX="1", TREZO_ADOPT_ORPHANS="0"):
        _sweep(c, **reads)
        assert len(_ledger_writes(c)) == 1
        # the row it just wrote is now in the table
        c.rows["paper_positions"][0].setdefault("id", "row-1")
        c.rows["paper_positions"][0]["status"] = "open"
        rep2, events2, _ = _sweep(c, **reads)
    assert len(_ledger_writes(c)) == 1, c.writes
    assert rep2["booked"] == 0, rep2


def test_nobl_shield_is_keyed_on_the_occ_not_the_underlying():
    """As specified with an underlying, the shield protects nothing on the
    lane that produced the acceptance case."""
    qa.reset_state()
    with _bound(), _reads(orders=[nobl_order(status="accepted")]), \
            quiet_activity_log():
        _run(qa.refresh_shield_for_book(ACCT3))
    assert qa.has_working_order(ACCT3, NOBL) is True
    assert qa.has_working_order(ACCT3, "NOBL") is False


def test_the_78_minute_silence_is_now_loud():
    """D1's I1: every working order is either young or loud. Nothing said
    anything while NOBL sat working for 78 minutes."""
    qa.reset_state()
    c = FakeClient(paper_positions=[])
    stuck = nobl_order(status="accepted", filled_qty="0")
    with _env(TREZO_QA_AUTOFIX="0", TREZO_QA_STUCK_MIN_OPTION="20"), \
            _patched(qa, _parse_ts=_ts_78_minutes_ago(stuck)):
        rep, events, sent = _sweep(c, positions=[], orders=[stuck], fills=[])
    assert "qa_order_stuck" in events, events
    codes = [f["finding"] for f in rep["findings"]]
    assert "qa_order_stuck" in codes, rep["findings"]
    assert not _ledger_writes(c), c.writes


def _ts_78_minutes_ago(order):
    """Pin the stuck order's submit time 78 minutes before now, so the test
    replays the real duration without depending on today's date."""
    import datetime as _dt
    real = qa._parse_ts
    target = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(minutes=78))

    def _p(v):
        if v == order["submitted_at"]:
            return target
        return real(v)
    return _p


# =========================================================================
# HOUSE RULE 3 -- a failed read must never read as empty
# =========================================================================


def test_positions_read_none_skips_the_whole_book():
    qa.reset_state()
    c = FakeClient(paper_positions=[])
    rep, events, _ = _sweep(c, positions=None, orders=[nobl_order()],
                            fills=[nobl_fill()])
    assert rep["skipped_reason"] and "positions" in rep["skipped_reason"], rep
    assert not _ledger_writes(c)
    assert "qa_skipped_unreadable" in events, events


def test_orders_read_none_skips_the_whole_book():
    qa.reset_state()
    c = FakeClient(paper_positions=[])
    rep, events, _ = _sweep(c, positions=[nobl_position()], orders=None,
                            fills=[nobl_fill()])
    assert rep["skipped_reason"] and "orders" in rep["skipped_reason"], rep
    assert not _ledger_writes(c)
    assert "qa_skipped_unreadable" in events, events


def test_fills_read_none_skips_the_whole_book():
    """The one that matters most: a positions read paired with a failed
    fills read is exactly the snapshot-only reasoning that lost NOBL."""
    qa.reset_state()
    c = FakeClient(paper_positions=[])
    rep, events, _ = _sweep(c, positions=[nobl_position()],
                            orders=[nobl_order()], fills=None)
    assert rep["skipped_reason"] and "fill" in rep["skipped_reason"], rep
    assert not _ledger_writes(c)


def test_a_skipped_book_never_reads_as_a_clean_one():
    qa.reset_state()
    c = FakeClient(paper_positions=[])
    rep, _, _ = _sweep(c, positions=None, orders=None, fills=None)
    assert set(qa.blank_report(ACCT3)) <= set(rep), rep
    assert rep["skipped_reason"] is not None
    assert rep["checked"] == 0 and rep["booked"] == 0, rep
    # The shield goes silent when QA cannot read, and BOTH reconcilers then
    # stop closing rows. That is the safe direction but a silent one, so the
    # absence gets a voice rather than only an absent log row.
    assert "qa_shield_stale" in [f["finding"] for f in rep["findings"]], rep


def test_unresolved_book_refuses_outright():
    qa.reset_state()
    c = FakeClient(paper_positions=[])
    with _bound(resolve=False), _quiet_alerts(), _reads(), \
            quiet_activity_log():
        rep = _run(qa.qa_sweep_for_book(c, "book-that-does-not-exist"))
    assert "unresolved" in (rep["skipped_reason"] or ""), rep
    assert not _ledger_writes(c)


def test_refused_route_writes_nothing():
    qa.reset_state()
    c = FakeClient(paper_positions=[])
    with _bound(ok=False), _quiet_alerts(), _reads(), quiet_activity_log():
        rep = _run(qa.qa_sweep_for_book(c, ACCT3))
    assert "route refused" in (rep["skipped_reason"] or ""), rep
    assert not _ledger_writes(c)


# =========================================================================
# HOUSE RULE 6 -- never fabricate a reconciliation
# =========================================================================


def test_a_cancelled_order_with_no_fills_creates_nothing():
    """No broker position either: there is simply nothing to book."""
    qa.reset_state()
    c = FakeClient(paper_positions=[])
    with _env(TREZO_QA_AUTOFIX="1", TREZO_ADOPT_ORPHANS="0"):
        rep, _, _ = _sweep(c, positions=[],
                           orders=[nobl_order(status="canceled",
                                              filled_qty="0")],
                           fills=[])
    assert rep["booked"] == 0 and not _ledger_writes(c), c.writes


def test_a_broker_position_with_no_receipt_is_flagged_never_invented():
    """'Not in the snapshot' is never a receipt -- and neither is 'the
    position is right there'. Without a fill record there is no qty, no
    price and no time that came from the venue."""
    qa.reset_state()
    c = FakeClient(paper_positions=[])
    with _env(TREZO_QA_AUTOFIX="1", TREZO_ADOPT_ORPHANS="0"):
        rep, events, _ = _sweep(c, positions=[nobl_position()],
                                orders=[nobl_order(status="canceled",
                                                   filled_qty="0")],
                                fills=[])
    assert not _ledger_writes(c), c.writes
    assert "qa_orphan_no_receipt" in [f["finding"] for f in rep["findings"]], rep
    assert rep["quarantined"] >= 1, rep


def test_two_candidate_orders_for_one_position_write_nothing():
    qa.reset_state()
    c = FakeClient(paper_positions=[])
    f2 = nobl_fill(id="act-2", order_id="0000aaaa-0000-0000-0000-000000000002",
                   qty="1", price="0.05")
    with _env(TREZO_QA_AUTOFIX="1", TREZO_ADOPT_ORPHANS="0"):
        rep, _, _ = _sweep(c, positions=[nobl_position(qty="-2", avg="0.05")],
                           orders=[nobl_order()], fills=[nobl_fill(), f2])
    assert not _ledger_writes(c), c.writes
    assert "qa_ambiguous_receipt" in [f["finding"] for f in rep["findings"]], rep


def test_arithmetic_mismatch_writes_nothing():
    """Two independent broker records must AGREE. stocks_reconcile has no
    such check, which is why it can close a row it never verified."""
    qa.reset_state()
    c = FakeClient(paper_positions=[])
    with _env(TREZO_QA_AUTOFIX="1", TREZO_ADOPT_ORPHANS="0"):
        rep, _, _ = _sweep(c, positions=[nobl_position(qty="-2")],
                           orders=[nobl_order()], fills=[nobl_fill()])
    assert not _ledger_writes(c), c.writes
    assert "qa_receipt_conflict" in [f["finding"] for f in rep["findings"]], rep


def test_price_disagreement_writes_nothing():
    qa.reset_state()
    c = FakeClient(paper_positions=[])
    with _env(TREZO_QA_AUTOFIX="1", TREZO_ADOPT_ORPHANS="0"):
        rep, _, _ = _sweep(c, positions=[nobl_position(avg="0.40")],
                           orders=[nobl_order()], fills=[nobl_fill()])
    assert not _ledger_writes(c), c.writes
    assert "qa_receipt_conflict" in [f["finding"] for f in rep["findings"]], rep


def test_a_round_trip_inside_the_window_is_quarantined_not_averaged():
    qa.reset_state()
    c = FakeClient(paper_positions=[])
    buy_back = nobl_fill(id="act-3", side="buy_to_close", price="0.02",
                         order_id="0000aaaa-0000-0000-0000-000000000003")
    with _env(TREZO_QA_AUTOFIX="1", TREZO_ADOPT_ORPHANS="0"):
        rep, _, _ = _sweep(c, positions=[nobl_position()],
                           orders=[nobl_order()], fills=[nobl_fill(), buy_back])
    assert not _ledger_writes(c), c.writes
    reasons = " ".join(f.get("reason", "") for f in rep["findings"])
    assert "round trip" in reasons, rep["findings"]


def test_a_multi_leg_order_is_never_booked_one_leg_at_a_time():
    """A spread booked leg by leg reads as a naked short."""
    qa.reset_state()
    c = FakeClient(paper_positions=[])
    mleg = nobl_order(order_class="mleg", legs=[
        {"id": "leg-a", "symbol": NOBL},
        {"id": "leg-b", "symbol": "NOBL260918P00050000"}])
    with _env(TREZO_QA_AUTOFIX="1", TREZO_ADOPT_ORPHANS="0"):
        rep, _, _ = _sweep(c, positions=[nobl_position()], orders=[mleg],
                           fills=[nobl_fill()])
    assert not _ledger_writes(c), c.writes
    f = [x for x in rep["findings"] if x["finding"] == "qa_multileg_refused"]
    assert f, rep["findings"]
    assert "NOBL260918P00050000" in f[0]["reason"], f


def test_the_over_book_guard_refuses_a_second_row():
    """Even a CLOSED row for the same ticker stops the create. Reopening or
    doubling up is where a re-adopt loop starts."""
    qa.reset_state()
    c = FakeClient(paper_positions=[
        {"id": "old-1", "user_id": ACCT3, "ticker": NOBL, "status": "closed",
         "side": "short", "quantity": 1, "entry_price": 0.05,
         "asset_type": "option", "broker_order_id": None}])
    with _env(TREZO_QA_AUTOFIX="1", TREZO_ADOPT_ORPHANS="0"):
        rep, _, _ = _sweep(c, positions=[nobl_position()],
                           orders=[nobl_order()], fills=[nobl_fill()])
    assert not _ledger_writes(c), c.writes
    f = [x for x in rep["findings"] if x["finding"] == "qa_overbook_refused"]
    assert f and "old-1" in f[0]["reason"], rep["findings"]


def test_a_row_is_never_closed_on_absence_alone():
    """The DOT/QYLD/AMZN loop: seven closes and seven re-adoptions in four
    days, every one of them decided by a symbol not being in a list."""
    qa.reset_state()
    c = FakeClient(paper_positions=[
        {"id": "r-1", "user_id": ACCT3, "ticker": "DOT", "status": "open",
         "side": "long", "quantity": 100, "entry_price": 4.0,
         "asset_type": "crypto", "broker_order_id": "o-dot",
         "entry_at": "2026-09-02T10:00:00Z", "close_requested": False}])
    qa._SHIELD[ACCT3] = {"ts": __import__("time").time(), "entries": {}}
    with _env(TREZO_QA_AUTOFIX="1", TREZO_ADOPT_ORPHANS="0"):
        rep, _, _ = _sweep(c, positions=[], orders=[], fills=[])
    assert not _ledger_writes(c), c.writes
    assert "qa_row_without_position" in [f["finding"] for f in rep["findings"]], rep


def test_a_closing_fill_is_the_only_thing_that_proves_a_close():
    qa.reset_state()
    c = FakeClient(paper_positions=[
        {"id": "r-2", "user_id": ACCT3, "ticker": "AMZN", "status": "open",
         "side": "long", "quantity": 10, "entry_price": 200.0,
         "asset_type": "stock", "broker_order_id": "o-amzn",
         "entry_at": "2026-09-02T10:00:00Z", "close_requested": False}])
    qa._SHIELD[ACCT3] = {"ts": __import__("time").time(), "entries": {}}
    sell = {"id": "act-9", "activity_type": "FILL", "type": "fill",
            "transaction_time": "2026-09-02T15:00:00Z", "price": "212.50",
            "qty": "10", "side": "sell", "symbol": "AMZN", "order_id": "o-x"}
    with _env(TREZO_QA_AUTOFIX="0"):
        rep, events, _ = _sweep(c, positions=[], orders=[], fills=[sell])
    assert "qa_phantom_close_proven" in events, events
    a5 = [w for w in rep["would_fix"] if w["action"] == "A5_close_receipted"]
    assert a5 and abs(a5[0]["exit_price"] - 212.50) < 1e-9, rep["would_fix"]
    assert not _ledger_writes(c), c.writes


def test_an_expired_short_put_is_bookkeeping_not_a_quarantine():
    """The wheel's normal, profitable ending emits no FILL at all. Without
    OPEXP every worthless CSP would raise a ticket that can never clear,
    and the channel Mike reads fills with permanent false positives."""
    qa.reset_state()
    c = FakeClient(paper_positions=[
        {"id": "r-3", "user_id": ACCT3, "ticker": NOBL, "status": "open",
         "side": "short", "quantity": 1, "entry_price": 0.05,
         "asset_type": "option", "broker_order_id": NOBL_ORDER,
         "entry_at": FILLED, "close_requested": False}])
    qa._SHIELD[ACCT3] = {"ts": __import__("time").time(), "entries": {}}
    exp = {"id": "act-e", "activity_type": "OPEXP", "symbol": NOBL,
           "qty": "1", "date": "2026-09-18", "side": "sell"}
    with _env(TREZO_QA_AUTOFIX="0"):
        rep, events, _ = _sweep(c, positions=[], orders=[], fills=[exp])
    assert "qa_row_without_position" not in [f["finding"] for f in rep["findings"]], rep
    assert any(w["action"] == "A5_close_expiry" for w in rep["would_fix"]), rep


# =========================================================================
# ARITHMETIC
# =========================================================================


def test_two_partial_fills_average_to_the_broker_price():
    qa.reset_state()
    c = FakeClient(paper_positions=[])
    pos = {"symbol": "XYZ", "asset_class": "us_equity", "qty": "100",
           "avg_entry_price": "10.20", "market_value": "1020"}
    o = {"id": "o-xyz", "symbol": "XYZ", "side": "buy", "qty": "100",
         "filled_qty": "100", "status": "filled", "type": "market",
         "order_class": "simple", "submitted_at": "2026-09-02T14:00:00Z",
         "filled_at": "2026-09-02T14:02:00Z", "asset_class": "us_equity"}
    f1 = {"id": "f1", "activity_type": "FILL", "type": "partial_fill",
          "transaction_time": "2026-09-02T14:01:00Z", "price": "10.10",
          "qty": "60", "side": "buy", "symbol": "XYZ", "order_id": "o-xyz"}
    f2 = dict(f1, id="f2", price="10.35", qty="40",
              transaction_time="2026-09-02T14:02:00Z")
    with _env(TREZO_QA_AUTOFIX="1", TREZO_ADOPT_ORPHANS="0"):
        rep, _, _ = _sweep(c, positions=[pos], orders=[o], fills=[f1, f2])
    w = _ledger_writes(c)
    assert len(w) == 1, c.writes
    assert w[0][2]["quantity"] == 100.0, w[0][2]
    assert abs(w[0][2]["entry_price"] - 10.20) < 1e-9, w[0][2]
    # The FIRST fill. This assertion said 14:02 -- the LAST one -- until
    # the 2026-09-02 review: a position opened by two partials was entered
    # at the first of them, and entry_at drives time stops, so booking the
    # last one moves an exit. See test_the_entry_time_is_the_first_fill.
    assert w[0][2]["entry_at"] == "2026-09-02T14:01:00Z", w[0][2]


def test_crypto_tolerances_are_relative_not_absolute():
    assert qa._qty_matches(0.000000015, 0.0000000150000001, "crypto")
    assert not qa._qty_matches(0.5, 0.5001, "crypto")
    assert qa._qty_matches(1.0, 1.0000005, "stock")


def test_an_option_price_unit_disagreement_is_named_not_swallowed():
    ok, note = qa._price_matches(0.05, 5.00, "option")
    assert not ok and "per-CONTRACT" in note, note


# =========================================================================
# SYMBOL SPELLING -- the duplicate-row generator
# =========================================================================


def test_ledger_symbol_agrees_with_adoption_the_platforms_own_rule():
    """One rule, enforced by the gate. Two rules is a duplicate BTC row."""
    cases = [({"symbol": "BTC/USD", "asset_class": "crypto"}, "crypto"),
             ({"symbol": "BTCUSD", "asset_class": "crypto"}, "crypto"),
             ({"symbol": "ETH/USD", "asset_class": "crypto"}, "crypto"),
             ({"symbol": "AAPL", "asset_class": "us_equity"}, "stock"),
             ({"symbol": NOBL, "asset_class": "us_option"}, "option")]
    for row, at in cases:
        assert qa.ledger_symbol(row["symbol"], at) == \
            adoption._ledger_ticker(row, at), row


def test_a_broker_crypto_position_matches_the_bare_ledger_row():
    """Built without this, the first crypto orphan gets a second row under
    a spelling the ledger does not use, and the monitor manages one coin
    from two rows."""
    qa.reset_state()
    c = FakeClient(paper_positions=[
        {"id": "r-btc", "user_id": ACCT3, "ticker": "BTC", "status": "open",
         "side": "long", "quantity": 0.5, "entry_price": 60000.0,
         "asset_type": "crypto", "broker_order_id": "o-btc",
         "entry_at": "2026-09-02T10:00:00Z", "close_requested": False}])
    pos = {"symbol": "BTC/USD", "asset_class": "crypto", "qty": "0.5",
           "avg_entry_price": "60000", "market_value": "30000"}
    with _env(TREZO_QA_AUTOFIX="1", TREZO_ADOPT_ORPHANS="0"):
        rep, _, _ = _sweep(c, positions=[pos], orders=[], fills=[])
    assert not _ledger_writes(c), c.writes
    assert "qa_orphan_no_receipt" not in [f["finding"] for f in rep["findings"]], rep


# =========================================================================
# THE SHIELD
# =========================================================================


def test_shield_returns_true_false_and_none():
    qa.reset_state()
    assert qa.has_working_order(ACCT3, NOBL) is None, "never swept -> unknown"
    with _bound(), _reads(orders=[nobl_order(status="accepted")]), \
            quiet_activity_log():
        _run(qa.refresh_shield_for_book(ACCT3))
    assert qa.has_working_order(ACCT3, NOBL) is True
    assert qa.has_working_order(ACCT3, "AAPL") is False
    qa._SHIELD[ACCT3]["ts"] -= (qa.shield_ttl_s() + 5)
    assert qa.has_working_order(ACCT3, NOBL) is None, "stale -> unknown"


def test_a_failed_orders_read_never_becomes_an_empty_shield():
    """Overwriting the entries with {} would turn one broker blip into a
    green light for every close on the book."""
    qa.reset_state()
    with _bound(), _reads(orders=[nobl_order(status="accepted")]), \
            quiet_activity_log():
        _run(qa.refresh_shield_for_book(ACCT3))
    with _bound(), _reads(orders=None), quiet_activity_log():
        out = _run(qa.refresh_shield_for_book(ACCT3))
    assert out["skipped_reason"], out
    assert qa.has_working_order(ACCT3, NOBL) is True, "kept, then ages out"


def test_a_resting_bracket_leg_does_not_shield():
    """Shielding on protection would return True for every bracketed stock
    row and silently switch stocks_reconcile's close path off."""
    qa.reset_state()
    parent = {"id": "p-1", "symbol": "AAPL", "status": "filled",
              "type": "market", "side": "buy", "asset_class": "us_equity",
              "submitted_at": "2026-09-02T14:00:00Z",
              "legs": [{"id": "leg-stop", "symbol": "AAPL"}]}
    leg = {"id": "leg-stop", "symbol": "AAPL", "status": "held",
           "type": "stop", "side": "sell", "asset_class": "us_equity",
           "submitted_at": "2026-09-02T14:00:00Z"}
    with _bound(), _reads(orders=[parent, leg]), quiet_activity_log():
        _run(qa.refresh_shield_for_book(ACCT3))
    assert qa.has_working_order(ACCT3, "AAPL") is False


def test_the_shield_is_per_book():
    qa.reset_state()
    with _bound(), _reads(orders=[nobl_order(status="accepted")]), \
            quiet_activity_log():
        _run(qa.refresh_shield_for_book(ACCT3))
    assert qa.has_working_order(ACCT3, NOBL) is True
    assert qa.has_working_order(ACCT2, NOBL) is None, "another book, no answer"


def test_a_working_order_past_the_bound_stays_shielded_and_gets_louder():
    """The design would have flipped the shield to False after 24h. That is
    a green light nobody gave; it escalates instead."""
    qa.reset_state()
    c = FakeClient(paper_positions=[])
    old = nobl_order(status="accepted", filled_qty="0",
                     submitted_at="2020-01-01T00:00:00Z")
    with _env(TREZO_QA_AUTOFIX="0"):
        rep, events, _ = _sweep(c, positions=[], orders=[old], fills=[])
    assert "qa_stale_working_order" in [f["finding"] for f in rep["findings"]], rep
    with _bound(), _reads(orders=[old]), quiet_activity_log():
        _run(qa.refresh_shield_for_book(ACCT3))
    assert qa.has_working_order(ACCT3, NOBL) is True


# Every path in the platform that closes a ledger row because the broker
# "does not list" its symbol. All FOUR must consult the shield.
#
# The first two were wired when the inspector shipped; the review of
# 2026-09-02 (BLOCKER 3) found that position_monitor holds the other two --
# and that those are the FAST ones, on the 60-second tick rather than the
# 30-minute reconcile, which is where the acceptance case would have gone
# first. A list, not a pair, so the next path added has somewhere to go.
_CLOSE_ON_ABSENCE_PATHS = (
    "app/agents/options_scanner.py",
    "app/paper/stocks_reconcile.py",
    "app/agents/position_monitor.py",     # stock/option AND crypto lanes
)


def test_every_call_site_skips_the_close_on_none_not_just_on_true():
    """None means 'could not check'. Read as False it is a green light, and
    the guard is one character away from being one: `if _shield:` would
    close on None. This is that character, asserted."""
    for rel in _CLOSE_ON_ABSENCE_PATHS:
        src = (AGENTS / rel).read_text(encoding="utf-8")
        assert "from app.paper.trade_qa import has_working_order" in src, rel
        assert "if _shield is not False:" in src, rel
        assert "qa_shield_error" in src, rel


def test_the_shield_is_bound_where_it_claims_to_be():
    """House rule 4: BUILT BUT NOT BOUND is the house failure mode.

    bootstrap's registry description and the module docstring both promise
    that Trezo will not close a row while an order for it is in flight.
    That promise is only kept where has_working_order is actually CALLED,
    so this asserts the call, not the import.
    """
    for rel in _CLOSE_ON_ABSENCE_PATHS:
        src = (AGENTS / rel).read_text(encoding="utf-8")
        assert "has_working_order(" in src, rel
    src = (AGENTS / "app/agents/book_health.py").read_text(encoding="utf-8")
    assert "trade_qa.refresh_shield_for_book(" in src, "nothing refreshes it"
    assert "trade_qa.qa_sweep_for_book(" in src, "nothing sweeps"


def test_the_monitors_two_absence_paths_both_reach_the_shield():
    """The specific hole BLOCKER 3 named: position_monitor closes on
    absence in TWO places -- the stock/option branch and the crypto lane --
    and a helper defined once but called once is still half-bound."""
    src = (AGENTS / "app/agents/position_monitor.py").read_text(encoding="utf-8")
    assert src.count('_qa_shield_blocks_close(r.get("user_id"), tk, r.get("side"))') == 2, (
        "both close-on-absence paths must consult the shield")
    # ...and it is consulted where the CLOSE is decided, not after it.
    for branch in ("crypto_symbol_variants(tk)", "tk.upper() not in alpaca_held"):
        i = src.index(branch)
        j = src.index("record_external_close", i)
        assert "_qa_shield_blocks_close" in src[i:j], (
            f"the shield is not consulted between {branch!r} and its close")


# =========================================================================
# BUDGETS, TICKETS, BACKLOG
# =========================================================================


def test_the_write_budget_defers_instead_of_running_away():
    qa.reset_state()
    c = FakeClient(paper_positions=[])
    positions, orders, fills = [], [], []
    for i in range(3):
        sym = f"SYM{i}"
        oid = f"o-{i}"
        positions.append({"symbol": sym, "asset_class": "us_equity",
                          "qty": "10", "avg_entry_price": "5.00"})
        orders.append({"id": oid, "symbol": sym, "side": "buy", "qty": "10",
                       "filled_qty": "10", "status": "filled",
                       "type": "market", "order_class": "simple",
                       "submitted_at": "2026-09-02T14:00:00Z",
                       "asset_class": "us_equity"})
        fills.append({"id": f"f-{i}", "activity_type": "FILL", "type": "fill",
                      "transaction_time": "2026-09-02T14:01:00Z",
                      "price": "5.00", "qty": "10", "side": "buy",
                      "symbol": sym, "order_id": oid})
    with _env(TREZO_QA_AUTOFIX="1", TREZO_ADOPT_ORPHANS="0",
              TREZO_QA_MAX_WRITES="2"):
        rep, events, _ = _sweep(c, positions=positions, orders=orders,
                                fills=fills)
    assert len(_ledger_writes(c)) == 2, c.writes
    assert rep["booked"] == 2, rep
    assert "qa_write_budget_hit" in events, events


def test_autofix_on_with_adoption_still_running_refuses_to_create():
    """Two creators racing on one orphan is the mistake this component
    exists to stop, arriving through the door the plan left open."""
    qa.reset_state()
    c = FakeClient(paper_positions=[])
    with _env(TREZO_QA_AUTOFIX="1", TREZO_ADOPT_ORPHANS="1"):
        rep, _, _ = _sweep(c, positions=[nobl_position()],
                           orders=[nobl_order()], fills=[nobl_fill()])
    assert not _ledger_writes(c), c.writes
    assert "qa_create_blocked_adoption" in [f["finding"] for f in rep["findings"]], rep


def test_tickets_are_edge_triggered_not_re_raised_every_sweep():
    """Without this the design writes thousands of identical rows a day and
    buries route_mismatch and execute_error in the log Mike reads."""
    qa.reset_state()
    c = FakeClient(paper_positions=[])
    reads = dict(positions=[nobl_position()],
                 orders=[nobl_order(status="canceled", filled_qty="0")],
                 fills=[])
    with _env(TREZO_QA_AUTOFIX="0"):
        _r1, ev1, sent1 = _sweep(c, **reads)
        _r2, ev2, sent2 = _sweep(c, **reads)
    assert ev1.count("qa_quarantine") == 1, ev1
    assert ev2.count("qa_quarantine") == 0, ev2
    assert len(sent1) >= 1 and len(sent2) == 0, (sent1, sent2)
    assert ev2.count("qa_sweep") == 1, "the sweep row still lands every time"


def test_tickets_are_keyed_per_book():
    qa.reset_state()
    c3 = FakeClient(paper_positions=[])
    c2 = FakeClient(paper_positions=[])
    reads = dict(positions=[nobl_position()],
                 orders=[nobl_order(status="canceled", filled_qty="0")],
                 fills=[])
    with _env(TREZO_QA_AUTOFIX="0"):
        _, _, s3 = _sweep(c3, uid=ACCT3, **reads)
        _, _, s2 = _sweep(c2, uid=ACCT2, **reads)
    assert s3 and s2, (s3, s2)
    assert s3[0][0] != s2[0][0], "one alert key per book"


def test_the_pre_existing_backlog_is_one_line_not_a_flood():
    qa.reset_state()
    rows = [{"id": f"legacy-{i}", "user_id": ACCT3, "ticker": t,
             "status": "open", "side": "long", "quantity": 1,
             "entry_price": 1.0, "asset_type": "stock",
             "broker_order_id": None, "entry_at": "2020-01-01T00:00:00Z",
             "close_requested": False}
            for i, t in enumerate(["NOK", "AGNC", "HPQ", "F", "XLE"])]
    c = FakeClient(paper_positions=rows)
    qa._SHIELD[ACCT3] = {"ts": __import__("time").time(),
                         "entries": {t: {"ids": ["x"]} for t in
                                     ["NOK", "AGNC", "HPQ", "F", "XLE"]}}
    with _env(TREZO_QA_AUTOFIX="0"):
        rep, events, _ = _sweep(c, positions=[], orders=[], fills=[])
    legacy = [f for f in rep["findings"] if f["finding"] == "qa_legacy_backlog"]
    assert len(legacy) == 1 and legacy[0]["count"] == 5, rep["findings"]
    assert not _ledger_writes(c), c.writes


# =========================================================================
# GEOMETRY -- checked, never written
# =========================================================================


def test_the_nobl_geometry_is_called_out_on_the_real_numbers():
    """0.315 against a 0.05 credit is 6.3x. Refusing to WRITE geometry is
    right; refusing to CHECK it is what leaves the position armed."""
    qa.reset_state()
    c = FakeClient(paper_positions=[
        {"id": "r-nobl", "user_id": ACCT3, "ticker": NOBL, "status": "open",
         "side": "short", "quantity": 1, "entry_price": 0.05,
         "stop_price": 0.315, "asset_type": "option",
         "broker_order_id": NOBL_ORDER, "entry_at": FILLED,
         "close_requested": False}])
    with _env(TREZO_QA_AUTOFIX="0"):
        rep, _, _ = _sweep(c, positions=[nobl_position()],
                           orders=[nobl_order()], fills=[nobl_fill()])
    f = [x for x in rep["findings"]
         if x["finding"] == "qa_stop_implies_outsized_loss"]
    assert f and f[0]["severity"] == "urgent", rep["findings"]
    assert "6.3x" in f[0]["reason"], f[0]["reason"]
    assert not _ledger_writes(c), c.writes


def test_a_normal_short_option_stop_is_not_flagged():
    qa.reset_state()
    c = FakeClient(paper_positions=[
        {"id": "r-ok", "user_id": ACCT3, "ticker": NOBL, "status": "open",
         "side": "short", "quantity": 1, "entry_price": 0.05,
         "stop_price": 0.10, "asset_type": "option",
         "broker_order_id": NOBL_ORDER, "entry_at": FILLED,
         "close_requested": False}])
    with _env(TREZO_QA_AUTOFIX="0"):
        rep, _, _ = _sweep(c, positions=[nobl_position()],
                           orders=[nobl_order()], fills=[nobl_fill()])
    assert "qa_stop_implies_outsized_loss" not in \
        [x["finding"] for x in rep["findings"]], rep["findings"]


def test_there_is_no_geometry_helper_in_the_module_at_all():
    """MUST-NOT, asserted structurally: there must be no _default_geometry
    equivalent for anyone to reach for later, and no code path that puts a
    stop or a target into a payload."""
    src = (AGENTS / "app/paper/trade_qa.py").read_text(encoding="utf-8")
    assert not hasattr(qa, "_default_geometry")
    assert '"stop_price":' not in src, "geometry must never be written"
    assert '"target_price":' not in src, "geometry must never be written"
    assert "record_external_position(" not in src, \
        "engine.record_external_position merges and rewrites geometry"


def test_the_module_never_writes_options_positions():
    src = (AGENTS / "app/paper/trade_qa.py").read_text(encoding="utf-8")
    assert src.count('table("options_positions")') == 1, src.count(
        'table("options_positions")')
    idx = src.index('table("options_positions")')
    assert src[idx:idx + 120].find(".select(") != -1, "read-only or nothing"


def test_the_module_never_touches_a_broker_order():
    src = (AGENTS / "app/paper/trade_qa.py").read_text(encoding="utf-8")
    for forbidden in ("place_order", "cancel_order", "submit_order",
                      "ratchet_stop", "liquidate", "_post("):
        assert forbidden not in src, forbidden


# =========================================================================
# THE STRICT READERS
# =========================================================================


def test_get_order_strict_separates_no_such_order_from_a_failed_read():
    async def _get_404(path, token=None, quiet_404=False):
        return alp.NOT_FOUND if quiet_404 else None

    async def _get_429(path, token=None, quiet_404=False):
        alp._note_read_error(path, "HTTP 429: rate limited", log=False)
        return None
    with quiet_activity_log():
        with _patched(alp, _get=_get_404):
            order, reason = _run(alp.get_order_strict("nope"))
        assert order is None and reason is None, (order, reason)
        with _patched(alp, _get=_get_429):
            order, reason = _run(alp.get_order_strict("boom"))
        assert order is None and reason and "429" in reason, (order, reason)


def test_a_404_does_not_poison_last_read_error_for_the_whole_book():
    """Probing ids is normal here. Noting each 404 would make an unrelated
    reconciler report a QA order probe as its reason for leaving a real
    position untouched."""
    async def _get_404(path, token=None, quiet_404=False):
        return alp.NOT_FOUND if quiet_404 else None
    with quiet_activity_log():
        alp._note_read_error("/v2/positions", "HTTP 500: upstream", log=False)
        before = alp.last_read_error()
        with _patched(alp, _get=_get_404):
            _run(alp.get_order_strict("some-order-id"))
        assert alp.last_read_error() == before, alp.last_read_error()


def test_an_unexhausted_orders_window_is_answerless():
    """A truncated evidence set is a failed read wearing a successful
    read's clothes: QA would report clean books it never inspected."""
    calls = {"n": 0}

    async def _get(path, token=None, quiet_404=False):
        calls["n"] += 1
        n = calls["n"]
        return [{"id": f"o-{n}-{i}", "symbol": "AAPL",
                 "submitted_at": f"2026-09-0{n}T00:0{i}:00Z"}
                for i in range(2)]
    with quiet_activity_log(), _patched(alp, _get=_get):
        out = _run(alp.get_orders_all_strict("2026-08-30T00:00:00Z", limit=2,
                                             max_pages=2))
    assert out is None, out


def test_an_exhausted_orders_window_comes_back_flattened():
    async def _get(path, token=None, quiet_404=False):
        return [{"id": "p1", "symbol": "AAPL", "status": "filled",
                 "submitted_at": "2026-09-02T14:00:00Z",
                 "legs": [{"id": "l1", "symbol": "AAPL", "status": "held",
                           "type": "stop"}]}]
    with quiet_activity_log(), _patched(alp, _get=_get):
        out = _run(alp.get_orders_all_strict("2026-08-30T00:00:00Z", limit=2))
    assert out is not None and {o["id"] for o in out} == {"p1", "l1"}, out


def test_an_unexhausted_activities_window_is_answerless():
    calls = {"n": 0}

    async def _get(path, token=None, quiet_404=False):
        calls["n"] += 1
        return [{"id": f"a-{calls['n']}-{i}", "symbol": "AAPL"}
                for i in range(2)]
    with quiet_activity_log(), _patched(alp, _get=_get):
        out = _run(alp.get_fill_activities_strict("2026-08-30T00:00:00Z",
                                                  page_size=2, max_pages=2))
    assert out is None, out


def test_the_activities_read_asks_for_expiry_and_assignment_too():
    seen = {}

    async def _get(path, token=None, quiet_404=False):
        seen["path"] = path
        return []
    with quiet_activity_log(), _patched(alp, _get=_get):
        _run(alp.get_fill_activities_strict("2026-08-30T00:00:00Z"))
    for t in ("FILL", "OPEXP", "OPASN", "OPEXC"):
        assert t in seen["path"], seen["path"]


def test_a_fills_parent_order_outside_the_window_is_resolved_by_id():
    """/v2/orders/{id} has no time filter, and it is the only thing that
    makes a multi-day position's order_class knowable."""
    qa.reset_state()
    c = FakeClient(paper_positions=[])
    fetched = {"n": 0}

    async def _one(oid):
        fetched["n"] += 1
        return (nobl_order(), None)
    with _env(TREZO_QA_AUTOFIX="1", TREZO_ADOPT_ORPHANS="0"):
        rep, _, _ = _sweep(c, positions=[nobl_position()], orders=[],
                           fills=[nobl_fill()], order_fn=_one)
    assert fetched["n"] == 1, fetched
    assert len(_ledger_writes(c)) == 1, c.writes


def test_an_answerless_order_probe_writes_nothing():
    qa.reset_state()
    c = FakeClient(paper_positions=[])

    async def _one(oid):
        return (None, "HTTP 429: rate limited")
    with _env(TREZO_QA_AUTOFIX="1", TREZO_ADOPT_ORPHANS="0"):
        rep, _, _ = _sweep(c, positions=[nobl_position()], orders=[],
                           fills=[nobl_fill()], order_fn=_one)
    assert not _ledger_writes(c), c.writes
    assert "qa_read_deferred" in [f["finding"] for f in rep["findings"]], rep


# =========================================================================
# REVIEW 2026-09-02 -- the three blockers and the three advisories.
#
# Each test below fails against the code as it stood before the review;
# the reproduction that motivated it is named in the docstring.
# =========================================================================


# ---- BLOCKER 1: the entry time written into the ledger -------------------

def test_an_expiry_activity_can_never_become_the_entry_time():
    """BLOCKER 1(a). The receipt's filled_at was max(transaction_time) over
    ALL activities for the symbol in the window -- not over the fills the
    arithmetic gate actually reconciled.

    An OPEXP carries no `side`, so it lands in NEITHER partition of
    _arith_gate and never trips the round-trip guard. Driven against the
    pre-fix module with one FILL at 18:25:20Z plus an OPEXP dated
    2026-09-30, the created row got entry_at = 2026-09-30T21:00:00Z: a
    timestamp no fill supports, written straight into paper_positions and
    into source_payload.qa.receipt, on the ONE write path this module has.
    House rule 6 in a single value.
    """
    qa.reset_state()
    c = FakeClient(paper_positions=[])
    opexp = {"id": "act-2", "activity_type": "OPEXP", "symbol": NOBL,
             "transaction_time": "2026-09-30T21:00:00Z", "qty": "1",
             "price": "0"}
    with _env(TREZO_QA_AUTOFIX="1", TREZO_ADOPT_ORPHANS="0"):
        rep, _ev, _s = _sweep(c, positions=[nobl_position()],
                              orders=[nobl_order()],
                              fills=[nobl_fill(), opexp])
    w = _ledger_writes(c)
    assert len(w) == 1, c.writes
    p = w[0][2]
    assert p["entry_at"] == FILLED, (
        f"entry_at {p['entry_at']} is supported by no fill; the only FILL "
        f"was at {FILLED}")
    assert p["source_payload"]["qa"]["receipt"]["filled_at"] == FILLED, p


_PART_FIRST = "2026-09-02T14:00:00Z"
_PART_LAST = "2026-09-02T14:40:00Z"


def _two_partial_fills():
    """One position built by two partial fills forty minutes apart."""
    pos = {"symbol": "AAPL", "asset_class": "us_equity", "qty": "20",
           "avg_entry_price": "5.00"}
    o = {"id": "o-part", "symbol": "AAPL", "side": "buy", "qty": "20",
         "filled_qty": "20", "status": "filled", "type": "market",
         "order_class": "simple", "submitted_at": _PART_FIRST,
         "filled_at": _PART_LAST, "asset_class": "us_equity"}
    f1 = {"id": "f-1", "activity_type": "FILL", "type": "fill",
          "transaction_time": _PART_FIRST, "price": "5.00", "qty": "10",
          "side": "buy", "symbol": "AAPL", "order_id": "o-part"}
    f2 = dict(f1, id="f-2", transaction_time=_PART_LAST)
    return pos, o, [f1, f2]


def _book_the_partial_fill_case():
    qa.reset_state()
    c = FakeClient(paper_positions=[])
    pos, o, fills = _two_partial_fills()
    with _env(TREZO_QA_AUTOFIX="1", TREZO_ADOPT_ORPHANS="0"):
        _sweep(c, positions=[pos], orders=[o], fills=fills)
    w = _ledger_writes(c)
    assert len(w) == 1, c.writes
    return w[0][2]


def test_the_entry_time_is_the_first_fill_not_the_last():
    """BLOCKER 1(b). Two partial fills forty minutes apart: the position
    was ENTERED at the first one. The pre-fix module wrote the last.

    entry_at drives time stops (the module says so where it declines to
    correct it), so a max here silently moves an exit forty minutes.
    """
    payload = _book_the_partial_fill_case()
    assert payload["entry_at"] == _PART_FIRST, (
        f"booked the LAST fill ({payload['entry_at']}) as the entry time")
    assert payload["source_payload"]["qa"]["receipt"]["filled_at"] == _PART_FIRST


def test_a_row_qa_books_does_not_immediately_trip_its_own_drift_check():
    """BLOCKER 1(b), the other half. The write path used max(fill time)
    while I4's drift check uses min -- so QA booked a row and then, on the
    very next sweep, flagged its own row for qa_entry_time_drift against a
    reference it had itself refused to use. A component whose output fails
    its own invariant is not an inspector."""
    row = dict(_book_the_partial_fill_case(), id="row-created")
    pos, o, fills = _two_partial_fills()
    qa.reset_state()
    c = FakeClient(paper_positions=[row])
    with _env(TREZO_QA_AUTOFIX="0", TREZO_QA_ENTRY_DRIFT_MIN="15"):
        rep, _ev, _s = _sweep(c, positions=[pos], orders=[o], fills=fills)
    codes = [f["finding"] for f in rep["findings"]]
    assert "qa_entry_time_drift" not in codes, (
        f"QA flagged the row it had just written: {rep['findings']}")


def test_the_receipt_is_built_only_from_the_fills_the_gate_reconciled():
    """The structural half of BLOCKER 1: the timestamp is derived from
    _arith_gate's OWN return value, so a future change cannot re-derive it
    from a wider set by accident."""
    ok, why, qty, px, opening = qa._arith_gate(
        nobl_position(), [nobl_fill(),
                          {"id": "x", "activity_type": "OPEXP",
                           "symbol": NOBL, "qty": "1", "price": "0",
                           "transaction_time": "2026-09-30T21:00:00Z"}],
        "option")
    assert ok and qty == 1.0, (ok, why, qty)
    assert [f["id"] for f in opening] == ["act-1"], opening
    assert qa._entry_fill_at(opening, NOBL_ORDER) == FILLED
    # a fill belonging to some OTHER order is not this receipt's evidence
    assert qa._entry_fill_at(opening, "another-order") == ""


# ---- BLOCKER 2: the `after` query parameter ------------------------------

def _capture_paths(fn):
    """Drive a strict reader with _get patched, and return the URL STRINGS
    it actually built. The suites all patch qa._read_orders / _read_fills,
    so before this the real query string was never exercised by anything."""
    seen = []

    async def _get(path, token=None, quiet_404=False):
        seen.append(path)
        return []
    with quiet_activity_log(), _patched(alp, _get=_get):
        _run(fn())
    return seen


def _decoded(path, key):
    """What a standard form-decoder on the far side sees for one param."""
    import urllib.parse
    return urllib.parse.parse_qs(path.split("?", 1)[1]).get(key, [])


def test_the_window_start_is_z_form_not_a_plus_offset():
    """datetime.isoformat() yields '...+00:00'. '+' is a legal query
    sub-delimiter, so no HTTP client escapes it and a form-decoder reads it
    back as a SPACE."""
    after = qa._after_iso(72.0)
    assert after.endswith("Z") and "+" not in after, after


def test_the_orders_url_survives_a_form_decoder():
    """BLOCKER 2, the read the SHIELD depends on. If this 4xx's, _get
    returns None -> get_orders_all_strict returns None -> the shield never
    populates -> has_working_order answers None forever -> every wired
    reconciler refuses every close, permanently, with only a 30-minute
    qa_shield_stale row as the signal. Asserted on the URL STRING, because
    every other suite patches the reader and never builds one."""
    raw = "2026-08-30T22:25:06.904155+00:00"      # the pre-fix producer
    paths = _capture_paths(lambda: alp.get_orders_all_strict(raw))
    assert paths, "no request was built"
    for p in paths:
        assert "+" not in p, p
        assert _decoded(p, "after") == [raw], (
            f"a form-decoder does not get the timestamp back: "
            f"{_decoded(p, 'after')}")


def test_the_activities_url_survives_a_form_decoder():
    raw = "2026-08-30T22:25:06.904155+00:00"
    paths = _capture_paths(lambda: alp.get_fill_activities_strict(raw))
    assert paths, "no request was built"
    for p in paths:
        assert "+" not in p, p
        assert _decoded(p, "after") == [raw], _decoded(p, "after")


def test_the_shields_own_read_builds_a_decodable_url_end_to_end():
    """The two above test the reader; this one drives the SHIELD itself, so
    the producer and the consumer of the timestamp are pinned together."""
    seen = []

    async def _get(path, token=None, quiet_404=False):
        seen.append(path)
        return []
    qa.reset_state()
    with _bound(), quiet_activity_log(), _patched(alp, _get=_get):
        _run(qa.refresh_shield_for_book(ACCT3))
    assert seen, "the shield built no request at all"
    for p in seen:
        assert "+" not in p, p


# ---- ADVISORY A: what the shield actually asks the venue -----------------

def test_the_shield_asks_for_open_orders_not_a_72_hour_status_all_window():
    """ADVISORY A. status=all over 72h is 1-8 calls per book per five
    minutes, and past roughly 4000 orders in the window it can never be
    exhausted -- which returns None forever, which is total shield failure.
    The shield only ever asks 'is an entry WORKING?'."""
    seen = []

    async def _get(path, token=None, quiet_404=False):
        seen.append(path)
        return []
    qa.reset_state()
    with _bound(), quiet_activity_log(), _patched(alp, _get=_get):
        _run(qa.refresh_shield_for_book(ACCT3))
    assert len(seen) == 1, f"one call per book per refresh, got {len(seen)}"
    assert "status=open" in seen[0], seen[0]
    assert "status=all" not in seen[0], seen[0]
    assert "after=" not in seen[0], (
        "an open-orders read needs no time window -- that window IS the "
        f"truncation cliff: {seen[0]}")
    assert "nested=true" in seen[0], "child legs must still be visible"


def test_the_open_orders_read_is_still_strict_about_exhaustion():
    """Cheaper does not mean laxer: a full page is not proof there is
    nothing behind it (house rule 3)."""
    calls = {"n": 0}

    async def _get(path, token=None, quiet_404=False):
        calls["n"] += 1
        n = calls["n"]
        return [{"id": f"o-{n}-{i}", "symbol": "AAPL",
                 "submitted_at": f"2026-09-0{n}T00:0{i}:00Z"}
                for i in range(2)]
    with quiet_activity_log(), _patched(alp, _get=_get):
        out = _run(alp.get_open_orders_all_strict(limit=2, max_pages=2))
    assert out is None, out


def test_a_failed_open_orders_read_still_leaves_the_shield_alone():
    qa.reset_state()
    with _bound(), _reads(orders=[nobl_order(status="accepted")]), \
            quiet_activity_log():
        _run(qa.refresh_shield_for_book(ACCT3))
    assert qa.has_working_order(ACCT3, NOBL) is True
    with _bound(), _reads(orders=[], open_orders=None), quiet_activity_log():
        out = _run(qa.refresh_shield_for_book(ACCT3))
    assert out["skipped_reason"], out
    assert qa.has_working_order(ACCT3, NOBL) is True, "kept, then ages out"


# ---- ADVISORY B: edge-triggering has to reach the REPORT -----------------

def test_a_standing_finding_is_not_re_reported_to_book_health():
    """ADVISORY B. The activity row and the alert were edge-triggered, but
    rep['findings'] and the counters sat ABOVE the check. book_health
    extends its own findings with them and turns EACH into an AgentMessage,
    and bootstrap's _persist subscriber writes every bus message to
    Supabase -- so a standing condition was ~one persisted row per book per
    sweep, forever. Driving the real sweep twice pre-fix gave findings=49
    on BOTH passes against ONE alert."""
    qa.reset_state()
    c = FakeClient(paper_positions=[])
    reads = dict(positions=[nobl_position()],
                 orders=[nobl_order(status="canceled", filled_qty="0")],
                 fills=[])
    with _env(TREZO_QA_AUTOFIX="0"):
        r1, _e1, s1 = _sweep(c, **reads)
        r2, _e2, s2 = _sweep(c, **reads)
    assert len(r1["findings"]) == 1 and r1["flagged"] == 1, r1
    assert r1["quarantined"] == 1, r1
    assert len(s1) == 1 and len(s2) == 0, (s1, s2)
    assert r2["findings"] == [], (
        f"a standing condition was re-reported: {r2['findings']}")
    assert r2["flagged"] == 0 and r2["quarantined"] == 0, r2
    # ...and it is not LOST either: a human reading the report still sees it
    assert [f["finding"] for f in r2["standing"]] == ["qa_orphan_no_receipt"], r2


def test_the_legacy_backlog_line_is_not_re_reported_either():
    """It is a MIGRATION item. One line when the count changes, not one bus
    message per book per sweep for as long as the backlog exists."""
    qa.reset_state()
    rows = [{"id": f"legacy-{i}", "user_id": ACCT3, "ticker": t,
             "status": "open", "side": "long", "quantity": 1,
             "entry_price": 1.0, "asset_type": "stock",
             "broker_order_id": None, "entry_at": "2020-01-01T00:00:00Z",
             "close_requested": False}
            for i, t in enumerate(["NOK", "AGNC", "HPQ"])]
    c = FakeClient(paper_positions=rows)
    qa._SHIELD[ACCT3] = {"ts": __import__("time").time(),
                         "entries": {t: {"ids": ["x"]} for t in
                                     ["NOK", "AGNC", "HPQ"]}}
    with _env(TREZO_QA_AUTOFIX="0"):
        r1, _e1, _s1 = _sweep(c, positions=[], orders=[], fills=[])
        r2, _e2, _s2 = _sweep(c, positions=[], orders=[], fills=[])
    assert [f["finding"] for f in r1["findings"]] == ["qa_legacy_backlog"], r1
    assert r2["findings"] == [], r2["findings"]
    assert [f["finding"] for f in r2["standing"]] == ["qa_legacy_backlog"], r2


# ---- ADVISORY C: I5 must not cry wolf on protected rows ------------------

def _stock_row_with_a_stop(**over):
    r = {"id": "r-xle", "user_id": ACCT3, "ticker": "XLE", "status": "open",
         "side": "long", "quantity": 10, "entry_price": 90.0,
         "stop_price": 85.0, "asset_type": "stock",
         "broker_order_id": "o-old", "entry_at": "2026-08-28T14:00:00Z",
         "close_requested": False}
    r.update(over)
    return r


def _xle_position():
    return {"symbol": "XLE", "asset_class": "us_equity", "qty": "10",
            "avg_entry_price": "90.00"}


def _resting_stop_leg():
    return {"id": "leg-stop", "symbol": "XLE", "status": "held",
            "type": "stop", "side": "sell", "asset_class": "us_equity",
            "submitted_at": "2026-08-28T14:00:00Z"}


def test_a_stop_leg_older_than_the_window_is_not_called_unenforceable():
    """ADVISORY C. A bracket's stop leg is placed ONCE, when the entry goes
    on. Five live stock rows were 102-120 hours old, so their legs were
    outside the sweep's 72-hour historical window and I5 reported 'no
    resting stop at the broker' on rows that were protected. The evidence
    is the LIVE open-orders read now."""
    qa.reset_state()
    c = FakeClient(paper_positions=[_stock_row_with_a_stop()])
    with _env(TREZO_QA_AUTOFIX="0"):
        rep, _ev, _s = _sweep(c, positions=[_xle_position()], orders=[],
                              fills=[], open_orders=[_resting_stop_leg()])
    assert "qa_unenforceable_stop" not in [f["finding"] for f in rep["findings"]], \
        rep["findings"]


def test_a_stock_row_with_no_resting_stop_anywhere_is_still_flagged():
    """The control: the finding must still fire when it is TRUE."""
    qa.reset_state()
    c = FakeClient(paper_positions=[_stock_row_with_a_stop()])
    with _env(TREZO_QA_AUTOFIX="0"):
        rep, ev, _s = _sweep(c, positions=[_xle_position()], orders=[],
                             fills=[], open_orders=[])
    assert "qa_unenforceable_stop" in [f["finding"] for f in rep["findings"]], \
        rep["findings"]
    assert "qa_unenforceable_stop" in ev, ev


def test_i5_is_skipped_not_answered_when_the_live_order_read_fails():
    """Absence of evidence is not evidence of absence -- the module's whole
    thesis, applied to its own fourth read. A None open-orders read must
    withhold the flag, not raise it, and must not skip the rest of the
    sweep either (it authorises no write)."""
    qa.reset_state()
    c = FakeClient(paper_positions=[_stock_row_with_a_stop()])
    with _env(TREZO_QA_AUTOFIX="0"):
        rep, ev, _s = _sweep(c, positions=[_xle_position()], orders=[],
                             fills=[], open_orders=None)
    assert rep["skipped_reason"] is None, rep
    assert "qa_unenforceable_stop" not in [f["finding"] for f in rep["findings"]], \
        rep["findings"]
    assert "qa_read_deferred" in ev, ev


def test_no_unenforceable_stop_where_the_venue_holds_no_stop_by_construction():
    """ADVISORY C, the other half. Alpaca accepts no stop order on an
    option, so 'the broker has no resting stop' is a fact about the venue,
    not a finding about the row. Live this fired on NINE short option rows
    and could never have cleared on any of them -- a warning nobody can act
    on is a warning that trains Mike to stop reading the channel."""
    assert "option" in qa._NO_VENUE_STOP_CLASSES
    assert "crypto" in qa._NO_VENUE_STOP_CLASSES
    qa.reset_state()
    c = FakeClient(paper_positions=[
        {"id": "r-nobl", "user_id": ACCT3, "ticker": NOBL, "status": "open",
         "side": "short", "quantity": 1, "entry_price": 0.05,
         "stop_price": 0.315, "asset_type": "option",
         "broker_order_id": NOBL_ORDER, "entry_at": FILLED,
         "close_requested": False}])
    with _env(TREZO_QA_AUTOFIX="0"):
        rep, _ev, _s = _sweep(c, positions=[nobl_position()],
                              orders=[nobl_order()], fills=[nobl_fill()],
                              open_orders=[])
    assert "qa_unenforceable_stop" not in [f["finding"] for f in rep["findings"]], \
        rep["findings"]


# ---- the live state of the acceptance case, as it stands today -----------

def test_the_live_nobl_row_fires_the_geometry_alarm_not_the_create_path():
    """The orphan adopter has already claimed NOBL on 49acafdd, with the
    invented 0.315 stop. So on the first live sweep the create path is not
    exercised at all -- what fires is the 6.3x geometry alarm on the real
    numbers (sold for 0.05, stop 0.315), and NOTHING is written."""
    qa.reset_state()
    c = FakeClient(paper_positions=[
        {"id": "r-nobl", "user_id": ACCT3, "ticker": NOBL, "status": "open",
         "side": "short", "quantity": 1, "entry_price": 0.05,
         "stop_price": 0.315, "asset_type": "option", "strategy": "wheel",
         "broker_order_id": NOBL_ORDER, "entry_at": FILLED,
         "close_requested": False}])
    with _env(TREZO_QA_AUTOFIX="1", TREZO_ADOPT_ORPHANS="0"):
        rep, ev, sent = _sweep(c, positions=[nobl_position()],
                               orders=[nobl_order()], fills=[nobl_fill()],
                               open_orders=[])
    assert rep["booked"] == 0, "the create path must not run -- a row exists"
    assert not _ledger_writes(c), c.writes
    f = [x for x in rep["findings"]
         if x["finding"] == "qa_stop_implies_outsized_loss"]
    assert f and f[0]["severity"] == "urgent", rep["findings"]
    assert "6.3x" in f[0]["reason"] and "0.315" in f[0]["reason"], f[0]["reason"]
    assert "$26" in f[0]["reason"], (
        "the alarm must say what the stop costs in dollars: " + f[0]["reason"])
    assert any(k.endswith("qa_stop_implies_outsized_loss") for k, _s, _t in sent), sent


def test_a_receipt_with_no_fill_time_anywhere_books_nothing():
    """The last corner of BLOCKER 1. Quantity and price can reconcile
    while no record carries a TIME -- and entry_at drives time stops, so a
    blank or invented one is a written value the receipt does not settle.
    The paperwork has to say when, or nothing is booked."""
    qa.reset_state()
    c = FakeClient(paper_positions=[])
    fill = nobl_fill()
    fill.pop("transaction_time")
    with _env(TREZO_QA_AUTOFIX="1", TREZO_ADOPT_ORPHANS="0"):
        rep, _ev, _s = _sweep(c, positions=[nobl_position()],
                              orders=[nobl_order(filled_at="")],
                              fills=[fill])
    assert not _ledger_writes(c), c.writes
    assert "qa_receipt_conflict" in [f["finding"] for f in rep["findings"]], \
        rep["findings"]


def test_the_orders_own_filled_at_is_an_acceptable_fallback():
    """It is still the VENUE's record, not an invention -- so a fill row
    with no timestamp does not block a booking the order itself dates."""
    qa.reset_state()
    c = FakeClient(paper_positions=[])
    fill = nobl_fill()
    fill.pop("transaction_time")
    with _env(TREZO_QA_AUTOFIX="1", TREZO_ADOPT_ORPHANS="0"):
        _sweep(c, positions=[nobl_position()], orders=[nobl_order()],
               fills=[fill])
    w = _ledger_writes(c)
    assert len(w) == 1 and w[0][2]["entry_at"] == FILLED, c.writes



# --- RE-REVIEW 2026-09-02: a resting EXIT is not an entry in flight -------
# The shield's predicate excluded protective TYPES and child legs, but the
# most common resting order in this book is neither: a take-profit is a
# plain GTC limit with no order_class and no legs -- exactly what
# alpaca.ensure_crypto_take_profit posts, and the shape submit_oco_sell's
# PARENT takes. Counting one as an entry inverted the shield: it returned
# True forever for that symbol, so all four close-on-absence paths went
# silently off (a real phantom row was then neither closed nor flagged),
# and the same order raised an URGENT "working for 1800 minutes" alert
# because a GTC exit rests for days by design.

def _shield_with(orders):
    """Build the shield exactly as refresh_shield_for_book does."""
    import time as _t
    entries = {}
    for o in qa._mark_legs(orders):
        if not qa._is_entry_working(o):
            continue
        k = qa.ledger_symbol(o.get("symbol"), qa.asset_class_of(o))
        slot = entries.setdefault(k, {"ids": [], "oldest": None, "sides": []})
        slot["ids"].append(str(o.get("id")))
        slot["sides"].append(str(o.get("side") or "").lower())
    qa._SHIELD["bk"] = {"ts": _t.time(), "entries": entries}


def _order(**kw):
    base = {"status": "new", "qty": "1", "type": "limit",
            "submitted_at": "2026-09-01T00:00:00Z"}
    base.update(kw)
    return base


def test_a_resting_take_profit_does_not_shield_a_long_row():
    """The exact shape ensure_crypto_take_profit posts: plain GTC limit
    sell, no order_class, no legs."""
    _shield_with([_order(id="cryp-tp", symbol="DOT/USD", side="sell", qty="100")])
    assert qa.has_working_order("bk", "DOT", "long") is False


def test_an_oco_exit_parent_does_not_shield():
    """submit_oco_sell's parent IS the resting sell limit, with the stop as
    its nested leg -- the shape alpaca documents as 'a lone resting sell
    limit'. Excluded by class AND by its protective child leg."""
    _shield_with([_order(id="oco-1", symbol="AAPL", side="sell", qty="10",
                         order_class="oco",
                         legs=[{"id": "oco-stop", "type": "stop", "side": "sell"}])])
    assert qa.has_working_order("bk", "AAPL", "long") is False


def test_a_shorts_protective_buy_limit_does_not_shield_the_short():
    _shield_with([_order(id="s-tp", symbol="XLF", side="buy", qty="37")])
    assert qa.has_working_order("bk", "XLF", "short") is False


def test_a_real_unfilled_entry_still_shields():
    """The NOBL order itself: a SELL that OPENS a short option row."""
    _shield_with([_order(id="entry-1", symbol=NOBL, side="sell", type="market",
                         submitted_at="2026-09-02T17:07:11Z")])
    assert qa.has_working_order("bk", NOBL, "short") is True


def test_an_unknown_row_side_keeps_the_safe_answer():
    """Not knowing which way the row runs must never become a green light
    to close it."""
    _shield_with([_order(id="cryp-tp", symbol="DOT/USD", side="sell", qty="100")])
    assert qa.has_working_order("bk", "DOT", None) is True


def test_a_resting_exit_is_not_reported_as_a_stuck_order():
    """A GTC take-profit resting for a day is not a stuck entry; alarming
    on one is the noise that teaches an owner to stop reading the channel."""
    import asyncio as _a
    from datetime import datetime as _dt, timezone as _tz
    rep = qa.blank_report("bk")
    tp = _order(id="cryp-tp", symbol="DOT/USD", side="sell", qty="100")
    now = _dt(2026, 9, 2, 6, 0, tzinfo=_tz.utc)   # 30h after submit
    with quiet_activity_log() as said:
        _a.new_event_loop().run_until_complete(
            qa._check_orders_stuck(None, "bk", [tp], now, rep,
                                   {("DOT", "long"): [{"id": "r1"}]}))
    events = [e for e, _t, _k in said]
    assert "qa_order_stuck" not in events and "qa_stale_working_order" not in events, said

if __name__ == "__main__":
    sys.exit(run_tests(dict(vars())))
