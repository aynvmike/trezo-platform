"""EXIT TRUTH guards (2026-09-18).

THE CASE IS REAL. On 09-18 at 13:07Z the venue quoted SOL 105.40/105.50.
The monitor priced it off a candle at 96.87 -- a days-old fallback bar --
called the stop hit on all three books, liquidated at the venue (real
fills 105.40-105.51) and booked every row at 96.87 x (1 - 5bps)
= 96.821565 with modelled fees: -$355.34 in the ledger for roughly -$30
of real loss, on a coin that never touched its stop. LINK repeated it at
13:42Z (-$60.81 booked; the fill was a whisker ABOVE entry). And every
broker-side close, all summer, moved the row's realized P/L while the
account's weekly counter never heard about it.

Three rules, each held here against the real code:
  1. A crypto stop is judged on a FRESH price -- the venue's quote, or a
     candle younger than a session -- or not at all. Not judged is a
     spoken row (price_unavailable), and the venue's resting stop keeps
     protecting.
  2. A liquidation is booked at the venue's filled_avg_price, read back
     by order id; unfilled waits (exit_pending); failed stays open. A
     broker close taken from receipts is labelled broker_fill; a candle
     stand-in is labelled candle_provisional. Never called a fill.
  3. Internal and external closes move the SAME account counters through
     ONE function.

Dependency-free (no pytest, no .env, no network).
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _bootstrap import load_module, run_tests, stub_config  # noqa: E402

stub_config()
engine = load_module("app.paper.engine")
pm = load_module("app.agents.position_monitor")
alog = load_module("app.agents.activity_log")


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@contextlib.contextmanager
def _patched(mod, **attrs):
    missing = object()
    old = {k: getattr(mod, k, missing) for k in attrs}
    try:
        for k, v in attrs.items():
            setattr(mod, k, v)
        yield
    finally:
        for k, v in old.items():
            if v is missing:
                if hasattr(mod, k):
                    delattr(mod, k)
            else:
                setattr(mod, k, v)


# --- a Supabase double deep enough for engine + monitor ------------------

class _Res:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, client, table):
        self._c, self._t, self._upd, self._single = client, table, None, False
        self._eq = {}

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self._eq[col] = val
        return self

    def limit(self, *_a, **_k):
        return self

    def maybe_single(self):
        self._single = True
        return self

    def update(self, payload):
        self._upd = dict(payload)
        return self

    def _match(self):
        rows = self._c.rows.get(self._t, [])
        return [r for r in rows if all(r.get(k) == v for k, v in self._eq.items())]

    def execute(self):
        if self._upd is not None:
            self._c.updates.append((self._t, dict(self._eq), self._upd))
            for r in self._match():
                r.update(self._upd)
            return _Res([])
        rows = self._match()
        if self._single:
            return _Res(rows[0] if rows else None)
        return _Res(list(rows))


class _Client:
    def __init__(self, rows):
        self.rows, self.updates = rows, []

    def table(self, name):
        return _Query(self, name)


def _iso(**kw):
    return (datetime.now(timezone.utc) - timedelta(**kw)).isoformat()


class _Quote:
    def __init__(self, bid, ask, ts):
        self.bid, self.ask, self.ts = bid, ask, ts


class _Said:
    def __init__(self):
        self.rows = []

    def __call__(self, event, ticker="", *_a, **kw):
        self.rows.append((str(event), str(ticker or "").upper(), kw))

    def events(self):
        return [e for e, _t, _k in self.rows]


def _row(**over):
    r = {"id": "pos-sol", "user_id": "book-b", "ticker": "SOL",
         "asset_type": "crypto", "side": "long", "quantity": 7.0446,
         "entry_price": 106.2, "stop_price": 100.0, "target_price": 112.0,
         "strategy": "crypto_swing", "entry_at": _iso(hours=4),
         "broker": "alpaca", "status": "open", "fees_usd": 1.87,
         "source_payload": {"adopted": False}}
    r.update(over)
    return r


# =========================================================================
# 1. A stop is judged on a FRESH price or not at all
# =========================================================================

def test_a_stale_venue_quote_is_no_price():
    async def _q(_tk):
        return _Quote(105.4, 105.5, _iso(minutes=30))
    with _patched(pm, _crypto_quote=_q):
        px, why = _run(pm._venue_price_crypto("SOL"))
    assert px is None and "stale" in why, (px, why)


def test_a_fresh_venue_quote_prices_the_mid():
    async def _q(_tk):
        return _Quote(105.4, 105.5, _iso(seconds=5))
    with _patched(pm, _crypto_quote=_q):
        px, src = _run(pm._venue_price_crypto("SOL"))
    assert abs(px - 105.45) < 1e-9 and src == "venue", (px, src)


def test_a_days_old_candle_cannot_price_a_coin():
    """The 09-18 shape: no venue quote, and the candle is a four-day
    fallback bar. 96.87 must never reach the stop comparison."""
    async def _q(_tk):
        return None

    async def _candle(_tk, _at):
        return 96.87

    async def _stale(_tk):
        return False, "last candle is 96h old"
    with _patched(pm, _crypto_quote=_q, _latest_price=_candle,
                  _candle_fresh=_stale):
        px, why = _run(pm._price_crypto("SOL"))
    assert px is None and "96h" in why, (px, why)


def test_a_live_candle_still_prices_when_the_venue_is_quiet():
    async def _q(_tk):
        return None

    async def _candle(_tk, _at):
        return 105.2

    async def _fresh(_tk):
        return True, "fresh"
    with _patched(pm, _crypto_quote=_q, _latest_price=_candle,
                  _candle_fresh=_fresh):
        px, src = _run(pm._price_crypto("SOL"))
    assert px == 105.2 and src == "candle"


def test_the_default_freshness_check_rejects_an_old_bar_and_accepts_a_live_one():
    class _Bar:
        def __init__(self, ts, close):
            self.timestamp, self.close = ts, close

    async def _old(_tk, _at):
        return [_Bar(datetime.now(timezone.utc) - timedelta(days=4), 96.87)]

    async def _live(_tk, _at):
        return [_Bar(datetime.now(timezone.utc) - timedelta(hours=5), 105.2)]
    with _patched(pm, fetch_candles_for=_old):
        ok, why = _run(pm._candle_is_fresh("SOL"))
        assert ok is False and "old" in why, (ok, why)
    with _patched(pm, fetch_candles_for=_live):
        ok, why = _run(pm._candle_is_fresh("SOL"))
        assert ok is True, (ok, why)


def test_no_price_is_said_once_and_throttled():
    said = _Said()
    pm._price_unavailable_at.clear()
    with _patched(alog, record=said):
        pm._say_price_unavailable("book-b", "SOL", "venue quote stale")
        pm._say_price_unavailable("book-b", "SOL", "venue quote stale")
    pm._price_unavailable_at.clear()
    assert said.events() == ["price_unavailable"], said.rows
    assert "NOT judged" in said.rows[0][2]["reason"]


# =========================================================================
# 2. A liquidation is booked at the venue's fill -- or waits
# =========================================================================

def _liq_harness(orders_by_poll, said):
    """get_order answers from a list, one entry per poll; sleep is free."""
    calls = {"n": 0, "closes": []}

    async def _get(_oid):
        i = min(calls["n"], len(orders_by_poll) - 1)
        calls["n"] += 1
        return orders_by_poll[i]

    async def _sleep(_s):
        return None

    async def _close(uid, pid, price, reason="stop", **kw):
        calls["closes"].append((uid, pid, price, reason, kw))
        return engine.FillResult(ok=True, position_id=pid, fill_price=price,
                                 realized_pnl_usd=0.0)
    return calls, dict(_get_order=_get, _sleep=_sleep, close_position=_close,
                       _supabase=lambda: _Client({"paper_positions": []}))


def test_a_filled_liquidation_is_booked_at_the_venues_fill_not_the_candle():
    said = _Said()
    calls, seams = _liq_harness(
        [{"id": "ord-1", "status": "accepted"},
         {"id": "ord-1", "status": "filled", "filled_avg_price": "105.51",
          "filled_qty": "7.0446"}], said)
    with _patched(pm, **seams), _patched(alog, record=said):
        fill = _run(pm._book_liquidation(_row(), {"id": "ord-1"}, 96.87, "stop"))
    assert fill is not None and fill.ok
    (uid, pid, price, reason, kw), = calls["closes"]
    assert price == 105.51, price                 # the fill, not 96.87
    assert kw.get("actual_fill") is True and kw.get("exit_order_id") == "ord-1", kw
    assert reason == "stop"


def test_an_unfilled_liquidation_is_parked_and_nothing_is_booked():
    said = _Said()
    calls, seams = _liq_harness([{"id": "ord-2", "status": "accepted"}], said)
    r = _row()
    with _patched(pm, **seams), _patched(alog, record=said):
        fill = _run(pm._book_liquidation(r, {"id": "ord-2"}, 96.87, "stop"))
    assert fill is None
    assert calls["closes"] == [], calls["closes"]
    pend = r["source_payload"].get("exit_pending")
    assert pend and pend["order_id"] == "ord-2" and pend["reason"] == "stop", r
    assert "exit_pending" in said.events(), said.events()


def test_a_rejected_liquidation_leaves_the_row_open_and_says_so():
    said = _Said()
    calls, seams = _liq_harness([{"id": "ord-3", "status": "rejected"}], said)
    r = _row()
    with _patched(pm, **seams), _patched(alog, record=said):
        fill = _run(pm._book_liquidation(r, {"id": "ord-3"}, 96.87, "stop"))
    assert fill is None and calls["closes"] == []
    assert "exit_pending" not in r["source_payload"]
    assert "exit_error" in said.events(), said.events()


def test_an_acceptance_with_no_order_id_closes_provisionally_and_labels_it():
    """The venue said yes and handed back nothing to read a fill from.
    The row must not be liquidated twice, so it closes -- but the exit
    is LABELLED a candle stand-in, never a fill."""
    said = _Said()
    calls, seams = _liq_harness([None], said)
    with _patched(pm, **seams), _patched(alog, record=said):
        fill = _run(pm._book_liquidation(_row(), object(), 105.2, "time"))
    assert fill is not None
    (uid, pid, price, reason, kw), = calls["closes"]
    assert price == 105.2 and not kw.get("actual_fill")
    assert "exit_provisional" in said.events(), said.events()


def test_a_parked_row_is_settled_from_its_order_and_not_rejudged():
    said = _Said()
    calls, seams = _liq_harness(
        [{"id": "ord-4", "status": "filled", "filled_avg_price": "105.40",
          "filled_qty": "7.0446"}], said)
    r = _row(source_payload={"exit_pending": {"order_id": "ord-4",
                                              "reason": "stop",
                                              "submitted_at": _iso(seconds=50)}})
    with _patched(pm, **seams), _patched(alog, record=said):
        handled = _run(pm._settle_pending_exit(r))
    assert handled is True
    (uid, pid, price, reason, kw), = calls["closes"]
    assert price == 105.4 and kw.get("actual_fill") is True and reason == "stop"


def test_a_parked_row_whose_order_died_goes_back_in_play():
    said = _Said()
    calls, seams = _liq_harness([{"id": "ord-5", "status": "canceled"}], said)
    r = _row(source_payload={"exit_pending": {"order_id": "ord-5",
                                              "reason": "stop",
                                              "submitted_at": _iso(seconds=50)}})
    with _patched(pm, **seams), _patched(alog, record=said):
        handled = _run(pm._settle_pending_exit(r))
    assert handled is False and calls["closes"] == []
    assert "exit_pending" not in r["source_payload"]


def test_a_row_with_nothing_pending_is_judged_normally():
    assert _run(pm._settle_pending_exit(_row())) is False


# =========================================================================
# 2b. A broker close is priced from the receipts
# =========================================================================

def test_receipts_price_an_external_close_from_the_closing_fills():
    """Two sells after entry summing to the row's quantity: the exit is
    their weighted average, labelled broker_fill, with the order id."""
    async def _reader(_after):
        return [
            {"id": "a1", "symbol": "SOL/USD", "side": "buy", "qty": "7.0446",
             "price": "106.2", "order_id": "entry", "transaction_time": _iso(hours=4)},
            {"id": "a2", "symbol": "SOL/USD", "side": "sell", "qty": "3.0",
             "price": "105.40", "order_id": "x-1", "transaction_time": _iso(minutes=9)},
            {"id": "a3", "symbol": "SOL/USD", "side": "sell", "qty": "4.0446",
             "price": "105.50", "order_id": "x-1", "transaction_time": _iso(minutes=8)},
        ]
    with _patched(pm, _fill_activities=_reader):
        px, src, oid = _run(pm._exit_receipt_price(_row()))
    want = (3.0 * 105.40 + 4.0446 * 105.50) / 7.0446
    assert src == "broker_fill" and oid == "x-1", (src, oid)
    assert abs(px - want) < 1e-9, (px, want)


def test_receipts_that_do_not_cover_the_row_refuse_to_price_it():
    async def _reader(_after):
        return [{"id": "a2", "symbol": "SOL/USD", "side": "sell", "qty": "1.0",
                 "price": "105.40", "order_id": "x", "transaction_time": _iso(minutes=9)}]
    with _patched(pm, _fill_activities=_reader):
        px, why, oid = _run(pm._exit_receipt_price(_row()))
    assert px is None and "sum" in why, (px, why)


def test_a_failed_receipts_read_is_answerless_not_a_price():
    async def _reader(_after):
        return None
    with _patched(pm, _fill_activities=_reader):
        px, why, oid = _run(pm._exit_receipt_price(_row()))
    assert px is None and "failed" in why


# =========================================================================
# 3. Two close paths, one ledger
# =========================================================================

def _books(row):
    acct = {"user_id": row["user_id"], "current_cash_usd": 1000.0,
            "today_realized_pnl_usd": 0.0, "ytd_realized_pnl_usd": 0.0,
            "week_realized_pnl_usd": 0.0, "consecutive_losses": 0}
    return _Client({"paper_positions": [dict(row)], "paper_accounts": [acct]})


def _account_update(client):
    ups = [u for t, _eq, u in client.updates if t == "paper_accounts"]
    assert len(ups) == 1, client.updates
    return ups[0]


def test_an_external_close_moves_the_account_counters_like_an_internal_one():
    """The defect: record_external_close moved the row and nothing else.
    Now both paths leave identical account deltas for the same exit."""
    async def _no_learn(**_k):
        return None
    row = _row()
    exit_px = 105.51
    fee = engine.commission("crypto", row["quantity"] * exit_px)
    pnl = row["quantity"] * (exit_px - row["entry_price"]) - fee - row["fees_usd"]

    c1 = _books(row)
    with _patched(engine, _supabase=lambda: c1), _patched(alog, record=_Said()):
        with _patched(load_module("app.learning.outcomes"), record_paper_close=_no_learn):
            r1 = _run(engine.record_external_close(
                row["user_id"], row["id"], exit_px, reason="alpaca_external",
                price_source="broker_fill", exit_order_id="x-1"))
    c2 = _books(row)
    with _patched(engine, _supabase=lambda: c2), _patched(alog, record=_Said()):
        with _patched(load_module("app.learning.outcomes"), record_paper_close=_no_learn):
            r2 = _run(engine.close_position(
                row["user_id"], row["id"], exit_px, reason="stop",
                actual_fill=True, exit_order_id="x-1"))
    assert r1.ok and r2.ok, (r1, r2)
    a1, a2 = _account_update(c1), _account_update(c2)
    for k in ("current_cash_usd", "today_realized_pnl_usd",
              "ytd_realized_pnl_usd", "week_realized_pnl_usd",
              "consecutive_losses"):
        assert abs(float(a1[k]) - float(a2[k])) < 1e-6, (k, a1[k], a2[k])
    assert abs(float(a1["today_realized_pnl_usd"]) - pnl) < 1e-6, (a1, pnl)
    assert abs(float(a1["current_cash_usd"]) - (1000.0 + row["quantity"] * exit_px - fee)) < 1e-6


def test_the_row_records_where_its_exit_price_came_from():
    async def _no_learn(**_k):
        return None
    row = _row()
    c = _books(row)
    with _patched(engine, _supabase=lambda: c), _patched(alog, record=_Said()), \
            _patched(load_module("app.learning.outcomes"), record_paper_close=_no_learn):
        _run(engine.record_external_close(row["user_id"], row["id"], 105.51,
                                          price_source="candle_provisional"))
    ups = [u for t, _eq, u in c.updates if t == "paper_positions"]
    assert ups and ups[0]["source_payload"]["exit_price_source"] == "candle_provisional"
    assert ups[0]["fees_usd"] > row["fees_usd"]          # the exit fee is charged


def test_a_venue_fill_is_booked_without_modelled_slippage():
    async def _no_learn(**_k):
        return None
    row = _row()
    c = _books(row)
    with _patched(engine, _supabase=lambda: c), _patched(alog, record=_Said()), \
            _patched(load_module("app.learning.outcomes"), record_paper_close=_no_learn):
        r = _run(engine.close_position(row["user_id"], row["id"], 105.51,
                                       reason="stop", actual_fill=True,
                                       exit_order_id="x-1"))
    assert r.fill_price == 105.51, r.fill_price       # not 105.51 x (1 - 5bps)
    ups = [u for t, _eq, u in c.updates if t == "paper_positions"]
    assert ups[0]["source_payload"]["exit_price_source"] == "broker_fill"
    assert ups[0]["source_payload"]["exit_order_id"] == "x-1"


def test_a_modelled_close_still_models_for_the_internal_engine():
    async def _no_learn(**_k):
        return None
    row = _row(broker="internal")
    c = _books(row)
    with _patched(engine, _supabase=lambda: c), _patched(alog, record=_Said()), \
            _patched(load_module("app.learning.outcomes"), record_paper_close=_no_learn):
        r = _run(engine.close_position(row["user_id"], row["id"], 105.51, reason="stop"))
    assert r.fill_price < 105.51                        # slippage applied
    ups = [u for t, _eq, u in c.updates if t == "paper_positions"]
    assert ups[0]["source_payload"]["exit_price_source"] == "modeled"


# =========================================================================
# 4. Bound, not just built (house rule 4): the sites actually call these
# =========================================================================

def test_the_crypto_liquidation_site_books_through_the_fill_path():
    src = inspect.getsource(pm)
    i = src.index("_liq, _cstat = await _throttled_liquidate(")
    block = src[i:i + 2500]
    assert "await _book_liquidation(" in block, "liquidation still books off the candle"
    assert "close_position(\n                            r[\"user_id\"], r[\"id\"], price_c" not in block


def test_both_external_close_sites_ask_the_receipts_first():
    src = inspect.getsource(pm)
    assert src.count("_exit_receipt_price(r)") >= 3, src.count("_exit_receipt_price(r)")
    assert src.count('price_source=_rx_src') >= 2


def test_the_crypto_price_path_is_the_fresh_one():
    src = inspect.getsource(pm)
    assert 'p, why = await _price_crypto(tk)' in src
    assert "if await _settle_pending_exit(r):" in src


def test_engine_has_one_account_update_path():
    """Neither close path touches paper_accounts itself any more."""
    for fn in (engine.close_position, engine.record_external_close):
        src = inspect.getsource(fn)
        assert "await _apply_close_to_account(" in src, fn.__name__
        assert 'table("paper_accounts")' not in src, (
            f"{fn.__name__} still updates the account inline")


if __name__ == "__main__":
    sys.exit(run_tests(dict(vars())))
