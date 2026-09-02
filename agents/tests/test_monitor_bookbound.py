"""Guards for the monitor's out-of-loop broker paths (audit 2026-09-01).

TE-12 / BI-07  The pre-holiday review and the open-bell gap check run
               at tick start, BEFORE the per-row account binding, and
               called leg_sync.resync_alpaca_legs -> get_positions /
               cancel_open_orders_for / submit_oco_sell UNBOUND. So the
               PRIMARY's exit legs for that symbol were cancelled and
               re-armed at another book's prices. The resync now binds
               the row's own book INSIDE and refuses an unknown book;
               its broker-truth read is STRICT (None = read failed = do
               nothing), never "no shares".
TE-11 / BI-06  Same-day option exits were submitted unbound. Each row
               binds its own book; rid is marked done only after an
               ACCEPTED order under that binding.
BI-05          The liquidation throttle / circuit was keyed by symbol
               alone, so one book's reject storm on a shared ticker
               silenced every other book's exit, and a tripped circuit
               never re-armed. Keys are per book per symbol; the
               circuit decays.
PH-3           The crypto gone-at-broker reconcile-close dropped its
               reason and was booked as 'alpaca_bracket'.
NEQ-05 / G3    A row whose source_payload carries no_price_stop (the
               dividend ladder) is a screen-managed hold. The monitor
               must not close it on stop/target, ratchet a trail onto
               it, arm a broker stop, run the naked check or show it to
               the reevaluator -- while external-fill detection and a
               manual close_requested still apply. One predicate,
               _is_no_price_stop(row), at every site; the flag must be
               SELECTed or the whole exemption is built and unbound.
REVIEW :28/:1545  The inline per-row binding is cleared after the loop.

Every test here drives the REAL function out of the real module (loaded
through _bootstrap, no engine boot) and stubs only the external seams
-- the broker, the database, the clock, the activity log. Module
attributes are patched through a contextmanager that always restores
them; nothing is planted in sys.modules.

Deliberately dependency-free (no pytest, no .env, no network) so the
deploy guard can run it in a bare checkout.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _bootstrap import load_module, run_tests, stub_config  # noqa: E402

stub_config()
# app.runtime must be stubbed BEFORE position_monitor imports
# app.runtime.asset_policy, or the real package __init__ boots the bus
# and the scheduler.
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
pm = load_module("app.agents.position_monitor")
# Seams the NEQ-05 real-tick tests pin: the equity session gate the
# broker-stop arm consults, and the holiday calendar the pre-break
# review consults. Both are lazy imports inside the monitor, so they
# are patched on their own modules.
ops_watchdog = load_module("app.agents.ops_watchdog")
options_scanner = load_module("app.agents.options_scanner")


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@contextlib.contextmanager
def _patched(mod, **attrs):
    """Swap module attributes and ALWAYS put the originals back. A
    sentinel, not None, marks "was absent" (rv:test-contract): a real
    attribute whose value is None must be restored, never deleted."""
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


def _norec(*_a, **_k):
    """activity_log.record stand-in: nothing written to disk."""
    return None


# --- two books, the way accounts.py would load them ---------------------

def _two_books():
    return [
        accounts.BrokerAccount(
            account_id="primary", label="Primary", owner_id="mike",
            account_key="book-a", key_id="A" * 26, secret="S" * 44),
        accounts.BrokerAccount(
            account_id="acct2", label="25k", owner_id="mike",
            account_key="book-b", key_id="B" * 26, secret="T" * 44),
    ]


@contextlib.contextmanager
def _registry(books):
    """Pin the account registry for ONE test, whatever an earlier suite in
    the shared run_all process left behind (test_book_scope installs a
    permanent fake three-book registry at import and never restores it,
    so accounts.load_accounts / account_for_user are not the real
    functions by the time this suite runs). Patch every name that reads
    the registry: the accounts module AND route_guard, which bound the
    names at import -- the same pattern test_manual_trade_bookbound
    uses. [] means single-account; two books means multi-account."""
    by_key = {b.account_key: b for b in books}
    multi = len(books) > 1

    def _for_user(uid):
        return by_key.get(str(uid or ""))

    def _skip(uid):                      # real should_skip_unresolved semantics
        return multi and _for_user(uid) is None

    # position_monitor bound should_skip_unresolved at import, so the
    # copy it holds (_pm_skip_unresolved) is pinned too.
    with _patched(accounts, load_accounts=lambda: list(books),
                  account_for_user=_for_user,
                  multi_account_active=lambda: multi,
                  primary_account=lambda: (books[0] if books else None),
                  should_skip_unresolved=_skip), \
            _patched(route_guard, load_accounts=lambda: list(books),
                     account_for_user=_for_user,
                     multi_account_active=lambda: multi), \
            _patched(pm, _pm_skip_unresolved=_skip):
        accounts.clear_account()
        try:
            yield
        finally:
            accounts.clear_account()


def _bound_id():
    a = accounts.current_account()
    return a.account_id if a else None


# --- a Supabase double just deep enough for these functions -------------

class _Res:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, client, table):
        self._c, self._t, self._upd = client, table, None

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def update(self, payload):
        self._upd = dict(payload)
        return self

    def execute(self):
        if self._upd is not None:
            self._c.updates.append((self._t, self._upd))
            return _Res([])
        return _Res(list(self._c.rows.get(self._t, [])))


class _Client:
    def __init__(self, rows):
        self.rows, self.updates = rows, []

    def table(self, name):
        return _Query(self, name)


class _Candle:
    def __init__(self, close):
        self.close = close


def _stock_row(uid, **over):
    r = {"id": f"pos-{uid}", "ticker": "PYPL", "user_id": uid,
         "broker": "alpaca", "asset_type": "stock", "side": "long",
         "quantity": 10, "stop_price": 60.0, "target_price": 70.0}
    r.update(over)
    return r


# =======================================================================
# TE-12 / BI-07: resync_alpaca_legs binds the ROW's book, inside
# =======================================================================

def test_resync_binds_to_the_rows_book_not_the_one_already_bound():
    """The exact tick-start state: the primary is bound (as
    set_account_for_user leaves it), and a 25k row is resynced. Every
    broker call -- read, cancel, re-arm -- must land on the 25k."""
    seen = {}

    async def _pos(token=None):
        seen["read_on"] = _bound_id()
        return [{"symbol": "PYPL", "qty": "10"}]

    async def _cancel(sym):
        seen["cancel_on"] = _bound_id()
        return 1, None

    async def _open(sym):
        return []

    async def _oco(sym, qty, limit_price=None, stop_price=None):
        seen["oco_on"] = _bound_id()
        seen["oco"] = (sym, qty, limit_price, stop_price)
        return {"id": "o1"}, None

    with _registry(_two_books()), _patched(
            alp, alpaca_configured=lambda: True, get_positions_strict=_pos,
            cancel_open_orders_for=_cancel, get_open_orders_for=_open,
            submit_oco_sell=_oco), _patched(alog, record=_norec):
        accounts.set_account_for_user("book-a")        # primary bound
        ok, note = _run(leg_sync.resync_alpaca_legs(
            _stock_row("book-b"), why="guard", user_id="book-b"))
        after = _bound_id()
    assert ok, note
    assert seen["read_on"] == "acct2", seen
    assert seen["cancel_on"] == "acct2", seen
    assert seen["oco_on"] == "acct2", seen
    assert seen["oco"] == ("PYPL", 10.0, 70.0, 60.0), seen
    assert after == "primary", "the binding must be restored afterwards"


def test_resync_refuses_an_unknown_book_and_never_falls_to_the_primary():
    calls = []
    refused = []

    async def _pos(token=None):
        calls.append("read")
        return [{"symbol": "PYPL", "qty": "10"}]

    async def _cancel(sym):
        calls.append("cancel")
        return 1, None

    def _mm(ticker, user_id, note, where):
        refused.append((ticker, user_id, where))

    with _registry(_two_books()), _patched(
            alp, alpaca_configured=lambda: True, get_positions_strict=_pos,
            cancel_open_orders_for=_cancel), _patched(
            route_guard, record_mismatch=_mm), _patched(alog, record=_norec):
        accounts.set_account_for_user("book-a")        # primary bound
        ok, note = _run(leg_sync.resync_alpaca_legs(
            _stock_row("book-zzz"), why="guard", user_id="book-zzz"))
    assert not ok and "route refused" in note, note
    assert calls == [], f"an unknown book reached the broker: {calls}"
    assert refused == [("PYPL", "book-zzz", "leg_sync")], refused


def test_resync_refuses_a_row_that_names_no_book():
    calls = []

    async def _cancel(sym):
        calls.append("cancel")
        return 1, None

    with _registry([]), _patched(alp, alpaca_configured=lambda: True,
                                 cancel_open_orders_for=_cancel), \
            _patched(alog, record=_norec):
        ok, note = _run(leg_sync.resync_alpaca_legs(
            _stock_row("", user_id=""), why="guard"))
    assert not ok and "no book" in note, note
    assert calls == []


def test_resync_falls_back_to_the_rows_own_user_id_only():
    """An old-shape call (no user_id kwarg) still binds the ROW's book,
    never whatever happens to be bound."""
    seen = {}

    async def _pos(token=None):
        seen["read_on"] = _bound_id()
        return [{"symbol": "PYPL", "qty": "10"}]

    async def _cancel(sym):
        return 1, None

    async def _open(sym):
        return []

    async def _oco(sym, qty, limit_price=None, stop_price=None):
        seen["oco_on"] = _bound_id()
        return {"id": "o1"}, None

    with _registry(_two_books()), _patched(
            alp, alpaca_configured=lambda: True, get_positions_strict=_pos,
            cancel_open_orders_for=_cancel, get_open_orders_for=_open,
            submit_oco_sell=_oco), _patched(alog, record=_norec):
        accounts.set_account_for_user("book-a")
        ok, note = _run(leg_sync.resync_alpaca_legs(_stock_row("book-b")))
    assert ok, note
    assert seen == {"read_on": "acct2", "oco_on": "acct2"}, seen


# --- the strict read -----------------------------------------------------

def test_resync_takes_no_action_when_the_positions_read_fails():
    """None is 'the read FAILED', not 'no shares'. Cancelling legs on an
    answerless read strips protection from shares we cannot see."""
    calls = []
    logged = []

    async def _none(token=None):
        return None

    async def _cancel(sym):
        calls.append("cancel")
        return 1, None

    async def _oco(sym, qty, limit_price=None, stop_price=None):
        calls.append("oco")
        return {"id": "o1"}, None

    def _rec(event, ticker, **kw):
        logged.append(event)

    with _registry([]), _patched(
            alp, alpaca_configured=lambda: True, get_positions_strict=_none,
            cancel_open_orders_for=_cancel, submit_oco_sell=_oco), \
            _patched(alog, record=_rec):
        ok, note = _run(leg_sync.resync_alpaca_legs(
            _stock_row("book-a"), why="guard", user_id="book-a"))
    assert not ok and "read failed" in note, note
    assert calls == [], f"acted on a failed read: {calls}"
    assert "legs_resync_deferred" in logged, "a deferred resync must say so"


def test_resync_tells_a_failed_read_from_a_flat_answer():
    """[] and a list without the symbol are ANSWERS: no shares. Still no
    cancel (nothing to protect), but a different note."""
    calls = []

    async def _flat(token=None):
        return []

    async def _cancel(sym):
        calls.append("cancel")
        return 1, None

    with _registry([]), _patched(
            alp, alpaca_configured=lambda: True, get_positions_strict=_flat,
            cancel_open_orders_for=_cancel), _patched(alog, record=_norec):
        ok, note = _run(leg_sync.resync_alpaca_legs(
            _stock_row("book-a"), why="guard", user_id="book-a"))
    assert not ok and "no shares" in note, note
    assert "read failed" not in note
    assert calls == []


def test_resync_uses_the_strict_read_not_the_collapsing_one():
    """The plain get_positions() turns a failure into []. The resync must
    never call it: patch it to explode and prove it is not reached."""
    async def _boom(token=None):
        raise AssertionError("get_positions() (non-strict) was called")

    async def _none(token=None):
        return None

    with _registry([]), _patched(
            alp, alpaca_configured=lambda: True, get_positions=_boom,
            get_positions_strict=_none), _patched(alog, record=_norec):
        ok, note = _run(leg_sync.resync_alpaca_legs(
            _stock_row("book-a"), why="guard", user_id="book-a"))
    assert not ok and "read failed" in note, note


# =======================================================================
# TE-12: the gap check passes the ROW's user_id into the resync
# =======================================================================

def test_gap_check_resyncs_under_the_rows_own_book():
    rows = [{"id": "p1", "ticker": "AMZN", "user_id": "book-b",
             "side": "long", "quantity": 5, "entry_price": 100.0,
             "stop_price": 90.0, "target_price": 120.0,
             "asset_type": "stock", "broker": "alpaca"}]
    client = _Client({"paper_positions": rows})
    got = []

    async def _cnd(tk, at):
        return [_Candle(100.0), _Candle(95.0)]        # -5% gap at the open

    async def _resync(row, new_stop=None, new_target=None, why="", *,
                      user_id=None):
        got.append((row["ticker"], user_id, row["stop_price"]))
        return True, "ok"

    at_open = datetime(2026, 9, 1, 13, 45, tzinfo=timezone.utc)
    with _patched(pm, _utc_now=lambda: at_open, _GAP_DAY="",
                  fetch_candles_for=_cnd), \
            _patched(rsettings, _supabase=lambda: client), \
            _patched(leg_sync, resync_alpaca_legs=_resync), \
            _patched(alog, record=_norec):
        _run(pm._gap_check_open_bell())
    assert got == [("AMZN", "book-b", round(95.0 * 0.98, 4))], got
    assert client.updates == [("paper_positions",
                               {"stop_price": round(95.0 * 0.98, 4)})]


def test_every_resync_call_site_names_the_book():
    """BUILT BUT NOT BOUND guard: the parameter exists; prove every
    caller passes it. The pre-break review is time-gated on a real
    holiday calendar, so it is pinned here by its call text."""
    import re
    for rel in ("app/agents/position_monitor.py", "app/agents/reevaluator.py"):
        src = (Path(__file__).resolve().parents[1] / rel).read_text(
            encoding="utf-8", errors="replace")
        calls = [m.start() for m in re.finditer(r"await resync_alpaca_legs\(", src)]
        assert calls, f"{rel}: no resync call found"
        for i in calls:
            chunk = src[i:i + 260]
            assert "user_id=" in chunk, (
                f"{rel}: a resync call does not name the book:\n{chunk}")
    pm_src = (Path(__file__).resolve().parents[1]
              / "app/agents/position_monitor.py").read_text(
        encoding="utf-8", errors="replace")
    assert pm_src.count("await resync_alpaca_legs(") == 3, (
        "expected the pre-break, gap-check and profit-trail resyncs")


# =======================================================================
# TE-11 / BI-06: day-option exits are bound per row
# =======================================================================

def _opt_row(rid, uid):
    return {"id": rid, "user_id": uid, "underlying": "SPY",
            "option_type": "call", "strike": 500.0, "contracts": 1,
            "net_premium_usd": -100.0, "expiration": "2026-09-01"}


def test_day_option_exits_are_bound_per_row_and_done_only_when_accepted():
    rows = [_opt_row("o-a", "book-a"), _opt_row("o-b", "book-b"),
            _opt_row("o-x", "book-unknown")]
    client = _Client({"options_positions": rows})
    submitted = []
    skipped = []

    async def _quote(occ):
        return 1.5                       # entry 1.00 -> +50%: fast take

    async def _order(occ, ct, side, time_in_force="day", limit_price=None,
                     token=None):
        submitted.append((occ, side, _bound_id()))
        if _bound_id() == "acct2":
            return None, "rejected: insufficient contracts"
        return {"id": "ord-1"}, None

    def _rec(event, ticker, **kw):
        if event == "option_day_exit_skipped":
            skipped.append((kw.get("extra") or {}).get("user_id"))

    midday = datetime(2026, 9, 1, 16, 0, tzinfo=timezone.utc)
    pm._day_opt_done.clear()
    with _registry(_two_books()), \
            _patched(pm, _day_opt_last=0.0, _utc_now=lambda: midday), \
            _patched(rsettings, _supabase=lambda: client), \
            _patched(alp_data, get_option_quote=_quote), \
            _patched(alp, submit_option_order=_order), \
            _patched(alog, record=_rec):
        accounts.set_account_for_user("book-a")         # tick-start state
        _run(pm._manage_day_options())
        done = set(pm._day_opt_done)
    pm._day_opt_done.clear()
    assert [b for _, _, b in submitted] == ["primary", "acct2"], submitted
    assert all(s == "sell" for _, s, _ in submitted)
    assert "o-a" in done, "accepted order on the right book -> done"
    assert "o-b" not in done, "rejected order must retry next pass"
    assert "o-x" not in done and skipped == ["book-unknown"], (
        "an unresolved book is skipped with a logged reason, never routed "
        "to the primary")


def test_day_option_exit_refuses_when_the_route_guard_says_no():
    rows = [_opt_row("o-b", "book-b")]
    client = _Client({"options_positions": rows})
    submitted = []
    mismatches = []

    async def _quote(occ):
        return 1.5

    async def _order(*a, **k):
        submitted.append(a)
        return {"id": "ord-1"}, None

    def _mm(ticker, user_id, note, where):
        mismatches.append((ticker, user_id, where))

    midday = datetime(2026, 9, 1, 16, 0, tzinfo=timezone.utc)
    pm._day_opt_done.clear()
    with _registry(_two_books()), \
            _patched(pm, _day_opt_last=0.0, _utc_now=lambda: midday), \
            _patched(rsettings, _supabase=lambda: client), \
            _patched(alp_data, get_option_quote=_quote), \
            _patched(alp, submit_option_order=_order), \
            _patched(route_guard, check_route=lambda uid: (False, "guard says no"),
                     record_mismatch=_mm), \
            _patched(alog, record=_norec):
        _run(pm._manage_day_options())
        done = set(pm._day_opt_done)
    pm._day_opt_done.clear()
    assert submitted == [], "a refused route must not reach the broker"
    assert mismatches == [("SPY", "book-b", "day_options")], mismatches
    assert "o-b" not in done


# =======================================================================
# BI-05: liquidation throttle + circuit are per book per symbol
# =======================================================================

@contextlib.contextmanager
def _clean_liq():
    saved = (dict(pm._liq_attempt_at), dict(pm._liq_fail_count),
             dict(pm._liq_fail_at))
    pm._liq_attempt_at.clear()
    pm._liq_fail_count.clear()
    pm._liq_fail_at.clear()
    try:
        yield
    finally:
        pm._liq_attempt_at.clear()
        pm._liq_attempt_at.update(saved[0])
        pm._liq_fail_count.clear()
        pm._liq_fail_count.update(saved[1])
        pm._liq_fail_at.clear()
        pm._liq_fail_at.update(saved[2])


def test_two_books_liquidation_failures_do_not_share_a_circuit():
    attempts = []

    async def _reject(symbol, asset_type="stock"):
        attempts.append(symbol)
        return None, "rejected"

    with _clean_liq(), _patched(alp, liquidate_position=_reject), \
            _patched(pm, _LIQ_COOLDOWN_S=0), _patched(alog, record=_norec):
        for _ in range(pm._LIQ_MAX_FAILS):
            _, st = _run(pm._throttled_liquidate("GM", user_id="book-a"))
            assert st.startswith("error:"), st
        _, st = _run(pm._throttled_liquidate("GM", user_id="book-a"))
        assert st == "circuit_open", st
        # THE BUG: book-b's exit on the same ticker used to read
        # circuit_open here, having never failed once itself.
        _, st = _run(pm._throttled_liquidate("GM", user_id="book-b"))
        assert st.startswith("error:"), (
            f"book-b inherited book-a's open circuit: {st}")
        assert pm._liq_fail_count == {"book-a:GM": 3, "book-b:GM": 1}, (
            pm._liq_fail_count)
    assert len(attempts) == 4


def test_the_throttle_is_per_book_too():
    async def _ok(symbol, asset_type="stock"):
        return {"id": "liq"}, None

    with _clean_liq(), _patched(alp, liquidate_position=_ok), \
            _patched(alog, record=_norec):
        _, st = _run(pm._throttled_liquidate("GM", user_id="book-a"))
        assert st == "ok"
        _, st = _run(pm._throttled_liquidate("GM", user_id="book-a"))
        assert st == "throttled"
        _, st = _run(pm._throttled_liquidate("GM", user_id="book-b"))
        assert st == "ok", f"book-b was throttled by book-a's attempt: {st}"


def test_a_tripped_circuit_re_arms_after_the_reset_window():
    attempts = []

    async def _reject(symbol, asset_type="stock"):
        attempts.append(symbol)
        return None, "rejected"

    with _clean_liq(), _patched(alp, liquidate_position=_reject), \
            _patched(pm, _LIQ_COOLDOWN_S=0), _patched(alog, record=_norec):
        for _ in range(pm._LIQ_MAX_FAILS):
            _run(pm._throttled_liquidate("GM", user_id="book-a"))
        _, st = _run(pm._throttled_liquidate("GM", user_id="book-a"))
        assert st == "circuit_open"
        # Age the last failure past the window: the circuit must re-arm
        # and the next attempt must actually reach the broker.
        pm._liq_fail_at["book-a:GM"] = time.time() - pm._LIQ_FAIL_RESET_S - 1
        _, st = _run(pm._throttled_liquidate("GM", user_id="book-a"))
        assert st.startswith("error:"), f"circuit never re-armed: {st}"
        assert pm._liq_fail_count["book-a:GM"] == 1, pm._liq_fail_count
    assert len(attempts) == pm._LIQ_MAX_FAILS + 1


def test_an_unattributed_call_keys_under_the_bound_book():
    """stocks_reconcile binds a book and calls without user_id; that
    call must land in the bound book's slot, not a shared one."""
    async def _ok(symbol, asset_type="stock"):
        return {"id": "liq"}, None

    with _registry(_two_books()), _clean_liq(), \
            _patched(alp, liquidate_position=_ok), _patched(alog, record=_norec):
        accounts.set_account_for_user("book-b")
        _, st = _run(pm._throttled_liquidate("GM", "stock"))
        assert st == "ok"
        assert "book-b:GM" in pm._liq_attempt_at, pm._liq_attempt_at


def test_every_monitor_liquidate_call_names_the_book():
    """BUILT BUT NOT BOUND guard for the five call sites in the tick."""
    import re
    src = (Path(__file__).resolve().parents[1]
           / "app/agents/position_monitor.py").read_text(
        encoding="utf-8", errors="replace")
    calls = [m.start() for m in re.finditer(r"await _throttled_liquidate\(", src)]
    assert len(calls) == 5, f"expected 5 liquidate call sites, found {len(calls)}"
    for i in calls:
        chunk = src[i:i + 140]
        assert "user_id=r.get(\"user_id\")" in chunk, (
            f"a liquidate call is not keyed by the row's book:\n{chunk}")


# =======================================================================
# PH-3: the crypto gone-at-broker close is booked as alpaca_external
# =======================================================================

def test_crypto_gone_at_broker_is_booked_as_alpaca_external():
    """Drive the REAL tick: one crypto row whose book no longer holds
    the coin at the broker. The ledger close must carry the reason the
    bus message already carried."""
    row = {"id": "c1", "user_id": "book-a", "ticker": "DOT",
           "asset_type": "crypto", "side": "long", "quantity": 100.0,
           "entry_price": 1.0, "stop_price": 0.8, "target_price": 1.5,
           "strategy": "crypto_swing",
           "entry_at": "2026-08-01T00:00:00+00:00", "broker": "alpaca",
           "close_requested": False}
    client = _Client({"paper_positions": [row]})
    seen = {}

    async def _rec_close(user_id, position_id, exit_price,
                         reason="alpaca_bracket"):
        seen.update(user_id=user_id, pid=position_id, reason=reason)
        return engine.FillResult(ok=True, position_id=position_id,
                                 fill_price=exit_price, realized_pnl_usd=10.0)

    async def _held(user_id, *, where="", max_age_s=None):
        seen["held_for"] = user_id
        return {"AMZN"}                  # this book holds no DOT

    async def _price(tk, at):
        return 1.1

    async def _noop():
        return None

    async def _nolock(user_id):
        return None

    agent = pm.PositionMonitorAgent()
    saved = (pm.PositionMonitorAgent._recon_tick_counter,
             pm.PositionMonitorAgent._did_initial_reconcile)
    pm.PositionMonitorAgent._recon_tick_counter = 0
    pm.PositionMonitorAgent._did_initial_reconcile = True
    try:
        with _registry([]), \
                _patched(pm, _supabase=lambda: client, _latest_price=_price,
                         _manage_day_options=_noop, _gap_check_open_bell=_noop,
                         _pre_break_review=_noop, check_and_lock_profit=_nolock), \
                _patched(book_scope, held_symbols=_held), \
                _patched(engine, record_external_close=_rec_close), \
                _patched(alog, record=_norec):
            out = _run(agent.tick())
    finally:
        (pm.PositionMonitorAgent._recon_tick_counter,
         pm.PositionMonitorAgent._did_initial_reconcile) = saved
        accounts.clear_account()
    assert seen.get("held_for") == "book-a", seen
    assert seen.get("pid") == "c1" and seen.get("user_id") == "book-a", seen
    assert seen.get("reason") == "alpaca_external", (
        f"crypto reconcile-close booked as {seen.get('reason')!r}")
    closes = [m for m in out if m.kind == "close"]
    assert closes and closes[0].payload["reason"] == "alpaca_external", out


# =======================================================================
# NEQ-05 / G3: a no_price_stop row gets no price management
# =======================================================================

_FLAG = {"no_price_stop": True}


def _row_for(uid, tk, **over):
    """An open long stock row at $50 with a $60 stop -- so any price
    below 60 is 'far below its stop'. Modeled by default; broker='alpaca'
    for the broker branch."""
    r = {"id": f"pos-{tk}", "user_id": uid, "ticker": tk,
         "asset_type": "stock", "side": "long", "quantity": 10,
         "entry_price": 50.0, "stop_price": 60.0, "target_price": 80.0,
         "strategy": "momentum", "entry_at": "2026-08-01T00:00:00+00:00",
         "broker": "paper", "close_requested": False}
    r.update(over)
    return r


@contextlib.contextmanager
def _real_tick(client, price, **extra):
    """Drive the REAL PositionMonitorAgent.tick() with only the external
    seams swapped: the DB, the price, the tick-start passes, the profit
    lock, the profit-step ladder's DB-backed counter, and the activity
    log. Anything in `extra` is patched onto the monitor too."""
    async def _price(tk, at):
        return price

    async def _noop():
        return None

    async def _nolock(user_id):
        return None

    async def _nostep(*_a, **_k):
        return False, 0          # keeps the step ladder off the database

    saved = (pm.PositionMonitorAgent._recon_tick_counter,
             pm.PositionMonitorAgent._did_initial_reconcile)
    pm.PositionMonitorAgent._recon_tick_counter = 0
    pm.PositionMonitorAgent._did_initial_reconcile = True
    try:
        with _patched(pm, _supabase=lambda: client, _latest_price=_price,
                      _manage_day_options=_noop, _gap_check_open_bell=_noop,
                      _pre_break_review=_noop, check_and_lock_profit=_nolock,
                      _step_check=_nostep, **extra), \
                _patched(alog, record=_norec):
            yield
    finally:
        (pm.PositionMonitorAgent._recon_tick_counter,
         pm.PositionMonitorAgent._did_initial_reconcile) = saved
        accounts.clear_account()


@contextlib.contextmanager
def _clean_naked():
    """The naked-check / stop-arm throttles, cleared for one test and
    restored after it."""
    saved = (dict(pm._naked_checked_at), dict(pm._naked_alerted_at),
             dict(pm._stop_armed_at))
    for d in (pm._naked_checked_at, pm._naked_alerted_at, pm._stop_armed_at):
        d.clear()
    try:
        yield
    finally:
        for d, s in zip((pm._naked_checked_at, pm._naked_alerted_at,
                         pm._stop_armed_at), saved):
            d.clear()
            d.update(s)


def test_the_predicate_reads_the_flag_and_nothing_else():
    f = pm._is_no_price_stop
    assert f({"source_payload": {"no_price_stop": True}})
    assert f({"source_payload": {"no_price_stop": "true"}})
    assert f({"source_payload": {"no_price_stop": 1}})
    assert f({"source_payload": '{"no_price_stop": true}'}), "jsonb as text"
    for row in ({}, {"source_payload": None}, {"source_payload": {}},
                {"source_payload": {"no_price_stop": False}},
                {"source_payload": {"no_price_stop": "false"}},
                {"source_payload": "not json"}, {"source_payload": 7},
                {"strategy": "dividend_lt"}):
        assert not f(row), f"flagged without the flag: {row}"


def test_a_flagged_modeled_row_far_below_a_stale_stop_is_not_closed():
    """THE CASE. Two modeled rows in one book at $10 against a $60 stop:
    the ordinary one closes on 'stop'; the no_price_stop one -- even
    with a stale stop_price sitting on the row -- is not closed, not
    trailed and never shown to the reevaluator."""
    rows = [_row_for("book-a", "KO"),
            _row_for("book-a", "PG", strategy="dividend_lt",
                     source_payload=dict(_FLAG))]
    client = _Client({"paper_positions": rows})
    closed, reeval_seen, trail_seen = [], [], []

    async def _close(user_id, pid, price, reason="stop"):
        closed.append((pid, reason))
        return engine.FillResult(ok=True, position_id=pid, fill_price=price,
                                 realized_pnl_usd=-400.0)

    async def _reeval(r, *a, **k):
        reeval_seen.append(r["ticker"])
        return None

    async def _trail(r, price, min_gain=None):
        trail_seen.append(r["ticker"])
        return None

    agent = pm.PositionMonitorAgent()
    with _registry([]), _real_tick(client, 10.0, close_position=_close,
                                   reeval_is_enabled=lambda: True,
                                   reevaluate_position=_reeval,
                                   _maybe_trail_stock_profit=_trail):
        out = _run(agent.tick())
    assert closed == [("pos-KO", "stop")], closed
    assert reeval_seen == ["KO"], f"the reevaluator saw a flagged row: {reeval_seen}"
    assert trail_seen == ["KO"], f"the trail touched a flagged row: {trail_seen}"
    assert [m.payload["ticker"] for m in out if m.kind == "close"] == ["KO"], out


def test_a_flagged_alpaca_row_gets_no_broker_stop_and_no_naked_check():
    """Broker branch, same $10-vs-$60 setup, both rows held at Alpaca.
    The ordinary row arms a stop (ensure_stock_protection), fails the
    naked check and has its orphan stop enforced at market. The flagged
    row: no arm, no orders query, no liquidation -- it is SUPPOSED to
    rest at the broker with no exit legs."""
    rows = [_row_for("book-a", "KO", broker="alpaca"),
            _row_for("book-a", "PG", broker="alpaca", strategy="dividend_lt",
                     source_payload=dict(_FLAG))]
    client = _Client({"paper_positions": rows})
    armed, asked, liquidated = [], [], []

    async def _held(user_id, *, where="", max_age_s=None):
        return {"KO", "PG"}

    async def _ensure(sym, qty, stop, target=None):
        armed.append((sym, stop))
        return True, "stop armed"

    async def _open(sym):
        asked.append(sym)
        return []                        # naked: no exit legs resting

    async def _liq(symbol, asset_type="stock"):
        liquidated.append(symbol)
        return {"id": "liq"}, None

    agent = pm.PositionMonitorAgent()
    with _registry([]), _clean_liq(), _clean_naked(), _real_tick(client, 10.0), \
            _patched(book_scope, held_symbols=_held), \
            _patched(alp, ensure_stock_protection=_ensure,
                     get_open_orders_for=_open, liquidate_position=_liq), \
            _patched(ops_watchdog, _us_market_open=lambda: True):
        out = _run(agent.tick())
    assert armed == [("KO", 60.0)], f"broker stop armed on the wrong rows: {armed}"
    assert asked == ["KO"], f"naked check ran on the wrong rows: {asked}"
    assert liquidated == ["KO"], f"liquidated the wrong rows: {liquidated}"
    assert not [m for m in out if m.kind == "close"], out
    pg = [m for m in out if m.payload.get("ticker") == "PG"]
    assert pg == [], f"a flagged row produced messages: {[m.payload for m in pg]}"


def test_a_manual_close_still_closes_a_flagged_row():
    rows = [_row_for("book-a", "PG", strategy="dividend_lt",
                     source_payload=dict(_FLAG), close_requested=True)]
    client = _Client({"paper_positions": rows})
    closed = []

    async def _close(user_id, pid, price, reason="stop"):
        closed.append((pid, reason))
        return engine.FillResult(ok=True, position_id=pid, fill_price=price,
                                 realized_pnl_usd=0.0)

    agent = pm.PositionMonitorAgent()
    with _registry([]), _real_tick(client, 10.0, close_position=_close,
                                   reeval_is_enabled=lambda: False):
        _run(agent.tick())
    assert closed == [("pos-PG", "manual")], closed


def test_external_fill_detection_still_applies_to_a_flagged_row():
    """The broker no longer holds it -> the ledger is reconciled, flag or
    no flag. Bookkeeping is not price management."""
    rows = [_row_for("book-a", "PG", broker="alpaca", strategy="dividend_lt",
                     source_payload=dict(_FLAG))]
    client = _Client({"paper_positions": rows})
    seen = {}

    async def _held(user_id, *, where="", max_age_s=None):
        return {"KO"}                    # PG is gone at the broker

    async def _rec_close(user_id, position_id, exit_price,
                         reason="alpaca_bracket"):
        seen.update(pid=position_id, reason=reason)
        return engine.FillResult(ok=True, position_id=position_id,
                                 fill_price=exit_price, realized_pnl_usd=1.0)

    agent = pm.PositionMonitorAgent()
    with _registry([]), _real_tick(client, 10.0), \
            _patched(book_scope, held_symbols=_held), \
            _patched(engine, record_external_close=_rec_close):
        out = _run(agent.tick())
    assert seen == {"pid": "pos-PG", "reason": "alpaca_bracket"}, seen
    assert [m.payload["reason"] for m in out if m.kind == "close"] == ["alpaca_bracket"]


def test_gap_check_leaves_a_flagged_row_alone_but_logs_the_read():
    """Same -5% open as the TE-12 gap test; the flagged row gets no
    tightened stop and no leg resync (either would plant the price stop
    it does not have), but the gap is still SEEN in the log."""
    rows = [{"id": "p1", "ticker": "AMZN", "user_id": "book-b",
             "side": "long", "quantity": 5, "entry_price": 100.0,
             "stop_price": 90.0, "target_price": 120.0,
             "asset_type": "stock", "broker": "alpaca",
             "source_payload": dict(_FLAG)}]
    client = _Client({"paper_positions": rows})
    got, logged = [], []

    async def _cnd(tk, at):
        return [_Candle(100.0), _Candle(95.0)]

    async def _resync(row, new_stop=None, new_target=None, why="", *,
                      user_id=None):
        got.append(row["ticker"])
        return True, "ok"

    def _rec(event, ticker, **kw):
        logged.append((event, ticker, kw.get("reason", "")))

    at_open = datetime(2026, 9, 1, 13, 45, tzinfo=timezone.utc)
    with _patched(pm, _utc_now=lambda: at_open, _GAP_DAY="",
                  fetch_candles_for=_cnd), \
            _patched(rsettings, _supabase=lambda: client), \
            _patched(leg_sync, resync_alpaca_legs=_resync), \
            _patched(alog, record=_rec):
        _run(pm._gap_check_open_bell())
    assert got == [], f"a flagged row was resynced: {got}"
    assert client.updates == [], client.updates
    assert any(e == "gap_check" and t == "AMZN" and "no_price_stop" in r
               for e, t, r in logged), logged


def test_pre_break_review_lets_a_flagged_red_row_ride_by_flag_not_by_name():
    """Two red 'momentum' rows on a break's eve -- neither matches the
    long-term name list. The ordinary one is sold into the break; the
    flagged one rides, because the flag is the contract."""
    # stop 40 < entry 50: NOT profit-locked, so the review's only reasons
    # to let a red row ride are the long-term name list or the flag.
    rows = [_row_for("book-a", "KO", stop_price=40.0),
            _row_for("book-a", "PG", stop_price=40.0, source_payload=dict(_FLAG))]
    client = _Client({"paper_positions": rows})
    logged = []

    async def _brk():
        return 3

    async def _cnd(tk, at):
        return [_Candle(10.0)]           # red: 10 vs entry 50

    def _rec(event, ticker, **kw):
        logged.append((event, ticker, kw.get("reason", "")))

    eve = datetime(2026, 9, 4, 18, 30, tzinfo=timezone.utc)
    with _patched(pm, _utc_now=lambda: eve, _PRE_BREAK_DAY="",
                  fetch_candles_for=_cnd), \
            _patched(options_scanner, _multi_day_break=_brk), \
            _patched(rsettings, _supabase=lambda: client), \
            _patched(alog, record=_rec):
        _run(pm._pre_break_review())
    assert client.updates == [("paper_positions", {"close_requested": True})], (
        client.updates)
    rode = [t for e, t, r in logged if e == "preholiday_review" and "rides" in r]
    sold = [t for e, t, r in logged if e == "preholiday_review" and "selling" in r]
    assert rode == ["PG"] and sold == ["KO"], logged


def test_the_flag_is_selected_and_consulted_where_it_is_read():
    """BUILT BUT NOT BOUND guard. The predicate is only as good as the
    SELECT that feeds it: every query the monitor and book_health read
    rows from must name source_payload, and the per-row decision must
    reach the sites it gates."""
    root = Path(__file__).resolve().parents[1]
    src = (root / "app/agents/position_monitor.py").read_text(
        encoding="utf-8", errors="replace")
    for anchor in ('"asset_type, broker, strategy, source_payload"',   # pre-break
                   '"asset_type, broker, source_payload"',             # gap check
                   'close_requested, source_payload")',                # the tick
                   "_nps = _is_no_price_stop(r)",
                   "if reeval_is_enabled() and not _nps:",
                   "if close_reason is None and not _nps:",
                   'if at == "stock" and not _nps:',
                   "elif _nps:"):
        assert anchor in src, f"position_monitor lost: {anchor}"
    bh_src = (root / "app/agents/book_health.py").read_text(
        encoding="utf-8", errors="replace")
    assert "stop_price, asset_type, source_payload" in bh_src
    assert "_is_no_price_stop(r)" in bh_src


# =======================================================================
# REVIEW :28/:1545: the inline binding does not outlive the loop
# =======================================================================

def test_the_tick_clears_its_inline_binding_when_the_loop_is_done():
    rows = [_row_for("book-b", "KO", quantity=1)]
    client = _Client({"paper_positions": rows})
    agent = pm.PositionMonitorAgent()
    with _registry(_two_books()), \
            _real_tick(client, 55.0, reeval_is_enabled=lambda: False):
        _run(agent.tick())
        left = accounts._active.get()
    assert left is None, f"the last row's book stayed bound: {left}"


if __name__ == "__main__":
    sys.exit(run_tests(dict(vars())))
