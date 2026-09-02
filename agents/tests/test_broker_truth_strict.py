"""OG-10 (audit 2026-09-01, rv:alpaca 1 / rv:bound-hunter 1): the option
broker-truth reconciler reads STRICT and BOUND, and the leg resync never
reads a failed cancel-verify as "legs gone" (rv:alpaca :136).

The blocker these replay: broker_truth._broker_option_symbols called the
DISPLAY read get_option_positions(), which collapses a failed read into
[]. Its `rows is None` guard was dead code. So a 429 or a timeout
reconciled the book against an EMPTY broker -- every live contract on
the book alarmed as a routing incident and every expired-OTM row closed
at 0 -- every 15 minutes, dry_run=False, on all three books. Built but
not bound: the strict read existed; nothing on this path called it.

What these pin, on the REAL module (tests/_bootstrap.load_module) with
only the seams swapped -- the account binder, the route check, the
broker reads, the Supabase client -- and always put back:
  * a None from the strict read -> skipped_reason, nothing closed,
    nothing flagged, ledger not even read;
  * the display read is never reached;
  * an unresolvable book is skipped with an 'unresolved book' reason and
    the broker is never asked on the primary's behalf;
  * a refused route is skipped and recorded under 'broker_truth';
  * a good read under the binding still closes the ONE unambiguous case
    and flags the rest -- the values arrive at the call site;
  * leg_sync: None from the cancel-verify aborts before submit_oco_sell;
    a later [] after a None still proceeds (break only on []).

No pytest, no .env, no network, no engine boot.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as _dt
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _bootstrap import load_module, run_tests, stub_config  # noqa: E402

stub_config()
alp = load_module("app.brokers.alpaca")
accounts = load_module("app.brokers.accounts")
route_guard = load_module("app.brokers.route_guard")
alog = load_module("app.agents.activity_log")
bt = load_module("app.paper.broker_truth")
leg_sync = load_module("app.paper.leg_sync")

import supabase  # noqa: E402  -- real package; only create_client is swapped


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


_MISSING = object()


@contextlib.contextmanager
def _patched(mod, **attrs):
    """Swap module attributes and ALWAYS put the originals back."""
    old = {k: getattr(mod, k, _MISSING) for k in attrs}
    try:
        for k, v in attrs.items():
            setattr(mod, k, v)
        yield
    finally:
        for k, v in old.items():
            if v is _MISSING:
                if hasattr(mod, k):
                    delattr(mod, k)
            else:
                setattr(mod, k, v)


# --- seams -------------------------------------------------------------------

class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, client, table):
        self.client, self.table_name = client, table
        self.op = ("select", None)
        self.eqs: list[tuple] = []

    def select(self, *_a, **_k):
        self.op = ("select", None)
        return self

    def update(self, payload):
        self.op = ("update", payload)
        return self

    def eq(self, k, v):
        self.eqs.append((k, v))
        return self

    def execute(self):
        return self.client._execute(self)


class FakeClient:
    """Rows in, writes out -- so a test can assert 'nothing was written'."""

    def __init__(self, tables: dict):
        self.tables = {k: list(v) for k, v in tables.items()}
        self.writes: list[dict] = []
        self.reads: list[str] = []

    def table(self, name):
        return _Query(self, name)

    def _execute(self, q: _Query):
        kind, payload = q.op
        if kind == "select":
            self.reads.append(q.table_name)
            rows = self.tables.get(q.table_name, [])
            return _Resp([r for r in rows
                          if all(r.get(k) == v for k, v in q.eqs)])
        self.writes.append({"table": q.table_name, "op": kind,
                            "payload": payload, "eq": list(q.eqs)})
        return _Resp([])


class _Binder:
    """bind_for_user stand-in: yields the book key, or None for a book it
    cannot resolve -- exactly the real contract."""

    def __init__(self, unresolvable=()):
        self.bound = None
        self.seen: list[str] = []
        self.unresolvable = set(unresolvable)

    @contextlib.contextmanager
    def __call__(self, user_id):
        uid = str(user_id)
        self.seen.append(uid)
        prev, self.bound = self.bound, uid
        try:
            yield None if uid in self.unresolvable else uid
        finally:
            self.bound = prev


UID = "acct3-book"
EXPIRED_OTM = "BMY260821P00061000"     # the real 8/21 drift row
LIVE_HELD = "AGNC300117P00010500"      # tracked AND held at the broker
LIVE_MISSING = "PG300117P00138000"     # tracked, NOT at the broker: incident
ORPHAN = "T300117P00023000"            # held, no ledger row


def _ledger(uid=UID):
    return {
        "paper_accounts": [{"user_id": uid}],
        "paper_positions": [
            {"id": 1, "user_id": uid, "ticker": EXPIRED_OTM, "side": "short",
             "quantity": 1, "entry_price": 0.19, "entry_at": "2026-08-10",
             "asset_type": "option", "status": "open"},
            {"id": 2, "user_id": uid, "ticker": LIVE_HELD, "side": "short",
             "quantity": 2, "entry_price": 0.04, "entry_at": "2026-08-25",
             "asset_type": "option", "status": "open"},
            {"id": 3, "user_id": uid, "ticker": LIVE_MISSING, "side": "short",
             "quantity": 1, "entry_price": 1.20, "entry_at": "2026-08-25",
             "asset_type": "option", "status": "open"},
        ],
    }


@contextlib.contextmanager
def _seams(binder, strict, *, check=lambda uid: (True, "ok"),
           mismatches=None, display=None):
    async def _boom(token=None):
        raise AssertionError("get_option_positions() (display read) was called")

    async def _px(symbol):
        return 67.015 if symbol == "BMY" else None

    def _mm(ticker, uid, note, where):
        if mismatches is not None:
            mismatches.append((uid, note, where))

    with _patched(accounts, bind_for_user=binder), \
         _patched(route_guard, check_route=check, record_mismatch=_mm), \
         _patched(alp, get_option_positions_strict=strict,
                  get_option_positions=display or _boom), \
         _patched(bt, _underlying_price=_px):
        yield


# --- the blocker: a failed read takes no action -------------------------------

def test_a_failed_option_read_skips_the_book_and_touches_nothing():
    """None from the strict read is ANSWERLESS. Before this the display
    read handed back [] and every one of these three rows was acted on:
    BMY closed at 0, AGNC and PG alarmed as routing incidents."""
    binder = _Binder()
    reads = {"n": 0}

    async def _none(token=None):
        reads["n"] += 1
        assert binder.bound == UID, "strict read ran UNBOUND"
        return None

    client = FakeClient(_ledger())
    with _seams(binder, _none):
        rep = _run(bt.reconcile_options_for_book(client, UID))

    assert reads["n"] == 1
    assert rep["skipped_reason"] == "broker unreadable — took no action", rep
    assert rep["closed"] == [] and rep["flagged"] == [] and rep["orphans"] == []
    assert rep["checked"] == 0, "ledger must not even be compared"
    assert client.writes == [], client.writes
    assert client.reads == [], "took no action means no ledger read either"


def test_a_strict_read_that_raises_is_the_same_as_none():
    binder = _Binder()

    async def _raise(token=None):
        raise RuntimeError("429 Too Many Requests")

    client = FakeClient(_ledger())
    with _seams(binder, _raise):
        rep = _run(bt.reconcile_options_for_book(client, UID))
    assert rep["skipped_reason"] == "broker unreadable — took no action", rep
    assert client.writes == [] and rep["closed"] == [] and rep["flagged"] == []


def test_the_display_read_is_never_reached():
    """_seams patches get_option_positions to explode; a good strict
    answer must get all the way through without touching it."""
    binder = _Binder()

    async def _flat(token=None):
        return []

    client = FakeClient({"paper_accounts": [{"user_id": UID}],
                         "paper_positions": []})
    with _seams(binder, _flat):
        rep = _run(bt.reconcile_options_for_book(client, UID))
    assert rep["skipped_reason"] is None and rep["checked"] == 0, rep


# --- OG-10: every book is its own book -----------------------------------------

def test_an_unresolvable_book_is_skipped_and_never_read_on_the_primary():
    """bind_for_user yields None for a book it cannot resolve. Reading on
    would compare this book against the PRIMARY's account and declare
    every row phantom. Skip, say 'unresolved book', ask the broker
    nothing."""
    binder = _Binder(unresolvable={"ghost-book"})
    reads = {"n": 0}

    async def _strict(token=None):
        reads["n"] += 1
        return []

    client = FakeClient(_ledger("ghost-book"))
    with _seams(binder, _strict), \
         _patched(accounts, should_skip_unresolved=lambda uid: uid == "ghost-book"):
        rep = _run(bt.reconcile_options_for_book(client, "ghost-book"))

    assert binder.seen == ["ghost-book"]
    assert reads["n"] == 0, "asked the broker for a book it could not bind"
    assert rep["skipped_reason"].startswith("unresolved book"), rep
    assert rep["closed"] == [] and rep["flagged"] == [] and rep["orphans"] == []
    assert client.writes == [] and client.reads == []


def test_a_refused_route_is_skipped_and_recorded_under_broker_truth():
    binder = _Binder()
    reads = {"n": 0}
    mismatches: list = []

    async def _strict(token=None):
        reads["n"] += 1
        return []

    def _check(uid):
        return False, f"bound primary but book {uid[:8]} belongs to acct3"

    client = FakeClient(_ledger())
    with _seams(binder, _strict, check=_check, mismatches=mismatches):
        rep = _run(bt.reconcile_options_for_book(client, UID))

    assert reads["n"] == 0
    assert rep["skipped_reason"].startswith("route refused:"), rep
    assert mismatches == [(UID, f"bound primary but book {UID[:8]} belongs "
                                f"to acct3", "broker_truth")], mismatches
    assert client.writes == []


# --- the values arrive: a good bound read still does the real work ------------

def test_a_good_bound_read_closes_only_the_unambiguous_case():
    """Same three ledger rows, broker answers under the binding. BMY
    (expired, settled OTM at 67.015 vs 61 strike) closes with the premium
    kept; AGNC is held -> untouched; PG is live but missing -> flagged,
    never closed; T is held with no row -> orphan."""
    binder = _Binder()
    seen = {}

    async def _strict(token=None):
        seen["bound"] = binder.bound
        return [{"symbol": LIVE_HELD, "asset_class": "us_option", "qty": "-2"},
                {"symbol": ORPHAN, "asset_class": "us_option", "qty": "-1"}]

    client = FakeClient(_ledger())
    with _seams(binder, _strict):
        rep = _run(bt.reconcile_options_for_book(client, UID))

    assert seen["bound"] == UID
    assert rep["skipped_reason"] is None and rep["checked"] == 3, rep
    assert rep["closed"] == [{"symbol": EXPIRED_OTM, "realized": 19.0}], rep
    assert [f["symbol"] for f in rep["flagged"]] == [LIVE_MISSING], rep
    assert "routing incident" in rep["flagged"][0]["why"]
    assert [o["symbol"] for o in rep["orphans"]] == [ORPHAN], rep
    closes = [w for w in client.writes if w["op"] == "update"]
    assert len(closes) == 1 and closes[0]["eq"] == [("id", 1)], closes
    assert closes[0]["payload"]["status"] == "closed_expired"
    assert closes[0]["payload"]["realized_pnl_usd"] == 19.0
    assert closes[0]["payload"]["exit_at"].startswith("2026-08-21")


def test_all_books_counts_the_skipped_ones_and_keeps_going():
    """One book's failed read must not stop the others, and the summary
    must say a book was skipped rather than count it as clean."""
    binder = _Binder()

    async def _strict(token=None):
        return None if binder.bound == "acct2-book" else []

    client = FakeClient({
        "paper_accounts": [{"user_id": "acct2-book"}, {"user_id": UID}],
        "paper_positions": [],
    })
    with _seams(binder, _strict), \
         _patched(supabase, create_client=lambda *_a, **_k: client):
        out = _run(bt.reconcile_options_all_books())

    assert out["ok"] and out["books"] == 2, out
    assert out["skipped"] == 1, out
    assert binder.seen == ["acct2-book", UID]
    by = {r["user_id"]: r["skipped_reason"] for r in out["reports"]}
    assert by == {"acct2-book": "broker unreadable — took no action",
                  UID: None}, by
    assert client.writes == []


# --- rv:alpaca :136 -- leg_sync's cancel-verify -------------------------------

def _stock_row(uid="book-a"):
    return {"user_id": uid, "ticker": "PYPL", "broker": "alpaca",
            "asset_type": "stock", "side": "long", "quantity": 10,
            "stop_price": 60.0, "target_price": 70.0}


async def _nosleep(_s):
    return None


@contextlib.contextmanager
def _leg_seams(open_orders_seq, calls, logged):
    binder = _Binder()
    seq = list(open_orders_seq)

    async def _pos(token=None):
        return [{"symbol": "PYPL", "qty": "10"}]

    async def _cancel(sym):
        calls.append("cancel")
        return 1, None

    async def _open(sym):
        calls.append("verify")
        return seq.pop(0) if len(seq) > 1 else seq[0]

    async def _oco(sym, qty, limit_price=None, stop_price=None):
        calls.append("oco")
        return {"id": "o1"}, None

    async def _stop(sym, qty, stop_p):
        calls.append("stop")
        return {"id": "s1"}, None

    def _rec(event, ticker, **kw):
        logged.append(event)

    with _patched(accounts, bind_for_user=binder), \
         _patched(route_guard, check_route=lambda uid: (True, "ok"),
                  record_mismatch=lambda *a, **k: None), \
         _patched(alp, alpaca_configured=lambda: True,
                  get_positions_strict=_pos, cancel_open_orders_for=_cancel,
                  get_open_orders_for=_open, submit_oco_sell=_oco,
                  submit_stop_sell=_stop), \
         _patched(alog, record=_rec), \
         _patched(leg_sync, asyncio=types.SimpleNamespace(sleep=_nosleep)):
        yield


def test_resync_aborts_when_the_cancel_cannot_be_verified():
    """get_open_orders_for -> None on every poll: the legs may still be
    there. No OCO, no stop, no naked alert -- the old legs stand and the
    next pass retries. Before this `if not left` read None as 'gone'."""
    calls: list = []
    logged: list = []
    with _leg_seams([None], calls, logged):
        ok, note = _run(leg_sync.resync_alpaca_legs(
            _stock_row(), why="guard", user_id="book-a"))
    assert not ok and "could not verify" in note, note
    assert "oco" not in calls and "stop" not in calls, calls
    assert calls.count("verify") == 6, calls
    assert "legs_resync_deferred" in logged and "legs_naked_alert" not in logged


def test_resync_keeps_polling_after_a_none_and_proceeds_on_a_confirmed_empty():
    """Break only on []: one failed poll followed by a confirmed empty
    listing is a verified cancel, and the re-arm goes ahead."""
    calls: list = []
    logged: list = []
    with _leg_seams([None, []], calls, logged):
        ok, note = _run(leg_sync.resync_alpaca_legs(
            _stock_row(), why="guard", user_id="book-a"))
    assert ok, note
    assert calls == ["cancel", "verify", "verify", "oco"], calls
    assert "legs_resynced" in logged


if __name__ == "__main__":
    sys.exit(run_tests(dict(vars())))
