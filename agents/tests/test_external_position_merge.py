"""record_external_position must not merge across the no_price_stop line.

vf:no-price-stop-monitor (audit 2026-09-01, engine.py record_external_
position). The weighted-average merge keyed the open row on user/ticker/
side/status only, selected neither source_payload nor strategy, and
patched quantity/entry/stop/target onto the EXISTING row. So:

  (a) an ordinary add of a ticker into a book already holding it as a
      flagged no_price_stop ladder row was folded into that row, which
      kept the flag -- the monitor then ignored the add's stop for the
      whole row and never armed it at the broker: the added shares sat
      unprotected under a flag they never carried;
  (b) a ladder add into a book holding the ticker under an ordinary row
      was folded into the unflagged row and price-managed after all --
      the lane's contract silently lost.

Now the open-row read selects source_payload (and strategy), and when
the existing row and the incoming payload disagree on the flag -- read
by the SAME predicate the monitor uses, app.paper.no_price_stop -- the
add is NOT merged: it opens its own row. Matching sides merge exactly
as before (weighted entry, widest protection).

Every test drives the REAL record_external_position out of the real
engine module (loaded through _bootstrap, no engine boot) against a
Supabase double that honours the eq() filters and records every select,
update and insert. Module attributes are patched through a
contextmanager that always restores them; nothing is planted in
sys.modules. No pytest, no .env, no network.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _bootstrap import load_module, run_tests, stub_config  # noqa: E402

stub_config()
engine = load_module("app.paper.engine")
nps = load_module("app.paper.no_price_stop")
alog = load_module("app.agents.activity_log")


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@contextlib.contextmanager
def _patched(mod, **attrs):
    """Swap module attributes and ALWAYS put the originals back."""
    _missing = object()
    old = {k: getattr(mod, k, _missing) for k in attrs}
    try:
        for k, v in attrs.items():
            setattr(mod, k, v)
        yield
    finally:
        for k, v in old.items():
            if v is _missing:
                if hasattr(mod, k):
                    delattr(mod, k)
            else:
                setattr(mod, k, v)


# --- a Supabase double that honours eq() and records every write --------

class _Res:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, client, table):
        self._c, self._t = client, table
        self._op, self._payload, self._cols, self._filters = None, None, None, []

    def select(self, cols="*", *_a, **_k):
        self._op, self._cols = "select", cols
        return self

    def eq(self, col, val):
        self._filters.append((col, val))
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def update(self, payload):
        self._op, self._payload = "update", dict(payload)
        return self

    def insert(self, payload):
        self._op, self._payload = "insert", dict(payload)
        return self

    def execute(self):
        c = self._c
        if self._op == "select":
            c.selects.append((self._t, self._cols, list(self._filters)))
            rows = c.rows.get(self._t, [])
            return _Res([r for r in rows
                         if all(str(r.get(k)) == str(v) for k, v in self._filters)])
        if self._op == "update":
            c.updates.append((self._t, self._payload, list(self._filters)))
            return _Res([])
        if self._op == "insert":
            c.inserts.append((self._t, self._payload))
            return _Res([{**self._payload, "id": f"new-{len(c.inserts)}"}])
        raise AssertionError("query executed with no operation")


class _Client:
    def __init__(self, rows):
        self.rows = rows
        self.selects, self.updates, self.inserts = [], [], []

    def table(self, name):
        return _Query(self, name)


def _open_row(**over):
    """An open PG long in book-a: 4 @ $100, ordinary by default."""
    r = {"id": "pos-PG", "user_id": "book-a", "ticker": "PG", "side": "long",
         "status": "open", "quantity": 4, "entry_price": 100.0,
         "stop_price": 95.0, "target_price": 120.0, "peak_price": None,
         "strategy": "momentum", "source_payload": {"broker": "alpaca"}}
    r.update(over)
    return r


_LADDER_ROW = dict(strategy="dividend_lt", stop_price=None, target_price=None,
                   source_payload={"no_price_stop": True, "broker": "alpaca"})


def _record(client, **over):
    """Drive the REAL record_external_position for a PG add into book-a."""
    events = []

    def _rec(kind, ticker, **kw):
        events.append((kind, ticker, kw))

    kw = dict(user_id="book-a", ticker="PG", asset_type="stock", side="long",
              quantity=6, entry_price=110.0, stop_price=99.0,
              target_price=130.0, strategy="momentum", broker="alpaca",
              broker_order_id="ord-2", source_payload={"strategy": "momentum"})
    kw.update(over)
    with _patched(engine, _supabase=lambda: client), _patched(alog, record=_rec):
        res = _run(engine.record_external_position(**kw))
    return res, events


def _ladder_add(**over):
    kw = dict(strategy="dividend_lt", stop_price=None, target_price=None,
              source_payload={"no_price_stop": True, "strategy": "dividend_lt",
                              "max_notional": 420.0})
    kw.update(over)
    return kw


# =======================================================================
# mismatch -> a fresh insert, the existing row untouched
# =======================================================================

def test_an_ordinary_add_into_a_flagged_ladder_row_opens_its_own_row():
    """THE CASE (a). Book-a holds PG as a flagged ladder row with no stop.
    An ordinary momentum add of PG with a $99 stop must NOT be folded
    into it: the flagged row would keep the flag and the monitor would
    ignore the $99 stop for the added shares. It inserts its own row,
    stop and target intact, unflagged."""
    existing = _open_row(**_LADDER_ROW)
    client = _Client({"paper_positions": [existing]})
    res, events = _record(client)
    assert res.ok, res
    assert client.updates == [], f"merged across the flag: {client.updates}"
    assert len(client.inserts) == 1, client.inserts
    table, ins = client.inserts[0]
    assert table == "paper_positions"
    assert ins["quantity"] == 6 and ins["entry_price"] == 110.0
    assert ins["stop_price"] == 99.0 and ins["target_price"] == 130.0, ins
    assert ins["strategy"] == "momentum"
    assert not nps.payload_is_no_price_stop(ins["source_payload"]), ins
    assert res.position_id == "new-1" and res.position_id != existing["id"]
    # the ladder row is exactly as it was
    assert existing["quantity"] == 4 and existing["stop_price"] is None
    kinds = [(k, t) for k, t, _ in events]
    assert ("position_merge_refused", "PG") in kinds, kinds
    assert ("position_merged", "PG") not in kinds, kinds


def test_a_ladder_add_into_an_ordinary_row_opens_its_own_row():
    """THE CASE (b), reversed. Book-a holds PG under an ordinary row with
    a $95 stop. The dividend ladder's plain buy (stop None, target None,
    no_price_stop True) must NOT be folded into it -- the old stop would
    survive and the ladder's shares would be price-managed. Own row,
    flagged, no stop."""
    existing = _open_row()
    client = _Client({"paper_positions": [existing]})
    res, events = _record(client, **_ladder_add())
    assert res.ok, res
    assert client.updates == [], f"merged across the flag: {client.updates}"
    assert len(client.inserts) == 1, client.inserts
    _, ins = client.inserts[0]
    assert ins["stop_price"] is None and ins["target_price"] is None, ins
    assert ins["strategy"] == "dividend_lt"
    assert nps.payload_is_no_price_stop(ins["source_payload"]), ins
    assert ins["source_payload"]["broker_order_id"] == "ord-2"
    assert existing["stop_price"] == 95.0 and existing["quantity"] == 4
    assert ("position_merge_refused", "PG") in [(k, t) for k, t, _ in events]


def test_the_flag_on_the_existing_row_is_read_from_jsonb_text_too():
    """A driver that hands jsonb back as text must not turn a flagged
    row into an ordinary one at the boundary check."""
    existing = _open_row(**_LADDER_ROW)
    existing["source_payload"] = '{"no_price_stop": true, "broker": "alpaca"}'
    client = _Client({"paper_positions": [existing]})
    res, _ = _record(client)
    assert res.ok and client.updates == [] and len(client.inserts) == 1, (
        client.updates, client.inserts)


# =======================================================================
# match -> the weighted-average merge, exactly as before
# =======================================================================

def test_matching_ordinary_adds_still_merge_into_one_position():
    """Mike 2026-07-28: one position, one basis. 4 @ 100 + 6 @ 110 ->
    10 @ 106; stop keeps the widest (min for a long: 95), target the
    highest (130). No insert; the existing id comes back."""
    existing = _open_row()
    client = _Client({"paper_positions": [existing]})
    res, events = _record(client)
    assert res.ok and res.position_id == "pos-PG", res
    assert client.inserts == [], f"a matching add opened a new row: {client.inserts}"
    assert len(client.updates) == 1, client.updates
    table, patch, filters = client.updates[0]
    assert table == "paper_positions" and ("id", "pos-PG") in filters
    assert patch == {"quantity": 10.0, "entry_price": 106.0,
                     "stop_price": 95.0, "target_price": 130.0}, patch
    kinds = [(k, t) for k, t, _ in events]
    assert ("position_merged", "PG") in kinds and \
        ("position_merge_refused", "PG") not in kinds, kinds


def test_matching_flagged_adds_still_merge_and_stay_stopless():
    """Two ladder buys of PG in one book are one ladder position: merged,
    average entry, and the merged row still carries no price stop."""
    existing = _open_row(**_LADDER_ROW)
    client = _Client({"paper_positions": [existing]})
    res, _ = _record(client, **_ladder_add())
    assert res.ok and res.position_id == "pos-PG", res
    assert client.inserts == [], client.inserts
    assert len(client.updates) == 1, client.updates
    _, patch, _ = client.updates[0]
    assert patch["quantity"] == 10.0 and patch["entry_price"] == 106.0, patch
    assert patch["stop_price"] is None and patch["target_price"] is None, patch


def test_an_empty_book_inserts_whatever_the_flag_says():
    """No open row: the boundary check has nothing to compare and the
    add inserts -- flagged or not -- exactly as before."""
    for over in ({}, _ladder_add()):
        client = _Client({"paper_positions": []})
        res, events = _record(client, **over)
        assert res.ok and client.updates == [] and len(client.inserts) == 1
        assert not [e for e in events if e[0] == "position_merge_refused"], events


# =======================================================================
# built AND bound: the read that feeds the check names the flag
# =======================================================================

def test_the_open_row_read_selects_the_flag_and_keys_on_the_book():
    """The boundary check is only as good as the SELECT that feeds it. The
    real _find_open must name source_payload (and strategy), and it must
    still key on THIS book's open row of THIS ticker and side -- every
    book is its own book."""
    client = _Client({"paper_positions": [_open_row(**_LADDER_ROW)]})
    _record(client)
    reads = [(cols, filters) for t, cols, filters in client.selects
             if t == "paper_positions"]
    assert len(reads) == 1, client.selects
    cols, filters = reads[0]
    for c in ("source_payload", "strategy", "stop_price", "target_price",
              "quantity", "entry_price", "id"):
        assert c in cols, f"_find_open no longer selects {c}: {cols}"
    for f in (("user_id", "book-a"), ("ticker", "PG"), ("side", "long"),
              ("status", "open")):
        assert f in filters, f"_find_open lost the {f[0]} key: {filters}"


def test_another_books_flagged_row_does_not_steer_this_books_add():
    """Book-b holds PG as a ladder row; book-a holds nothing. Book-a's
    ordinary add inserts (there is no book-a row to merge into) and the
    refusal is not logged -- book-b's row was never in the picture."""
    client = _Client({"paper_positions": [_open_row(user_id="book-b",
                                                    **_LADDER_ROW)]})
    res, events = _record(client)
    assert res.ok and client.updates == [] and len(client.inserts) == 1
    assert not [e for e in events if e[0] == "position_merge_refused"], events


def test_the_engine_reads_the_flag_through_the_shared_predicate():
    """One reading of the flag, whichever side asks: the engine binds the
    predicate out of app.paper.no_price_stop, not a private copy."""
    assert engine._is_no_price_stop is nps.is_no_price_stop
    assert engine._payload_nps is nps.payload_is_no_price_stop
    assert nps.is_no_price_stop({"source_payload": {"no_price_stop": "yes"}})
    assert not nps.is_no_price_stop({"source_payload": "not json"})
    assert not nps.is_no_price_stop(None)


if __name__ == "__main__":
    sys.exit(run_tests(dict(vars())))
