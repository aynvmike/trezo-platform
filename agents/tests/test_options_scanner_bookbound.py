"""Book-bound options scanner guards (audit 2026-09-01).

The options scanner places real (paper) option orders, and until this
audit three of its paths acted with no idea WHICH book they were acting
for:

  TE-14 / NEQ-08  the hourly re-score selected EVERY book's open rows and
                  sent harvest / exit orders with no token and no account
                  binding -- so a 25k or 75k book's buy-back landed on
                  the PRIMARY Alpaca account.
  TE-15           the broker reconcile ran unbound, and its "skip a
                  failed read" branch was unreachable because the read
                  it used returned [] on failure.
  KS-6            the direct-fire lanes never consulted recovery, so a
                  book in weekly recovery kept buying the exact lanes
                  recovery suspends.
  NEQ-10          an expired short put with no settle-tick price fell
                  into the "full credit kept" branch and was booked as a
                  win.
  NEQ-09          the lanes read TREZO_PRIMARY_USER_ID with os.getenv,
                  which never sees agents/.env.

Every test here drives the REAL scanner methods (loaded from the module
file) with only the seams stubbed: the Supabase query chain, the Alpaca
helpers, the account binding, the route guard, the kill-switch read and
the activity log. Every stub is put back. Deliberately dependency-free
(no pytest, no .env, no network) so the deploy gate can run it in a bare
checkout, in one process with every other suite.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
import time
import types
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _bootstrap import load_module, run_tests, stub_config  # noqa: E402

stub_config()
scanner = load_module("app.agents.options_scanner")
alp = load_module("app.brokers.alpaca")
accounts = load_module("app.brokers.accounts")
route_guard = load_module("app.brokers.route_guard")
ks = load_module("app.paper.killswitch")
wt = load_module("app.integrations.web_tokens")
alp_data = load_module("app.brokers.alpaca_data")
act = load_module("app.agents.activity_log")
mu = load_module("app.data.market_universe")


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@contextlib.contextmanager
def _patched(mod, **attrs):
    """Swap module/class attributes and ALWAYS put the originals back."""
    old = {k: getattr(mod, k) for k in attrs}
    try:
        for k, v in attrs.items():
            setattr(mod, k, v)
        yield
    finally:
        for k, v in old.items():
            setattr(mod, k, v)


@contextlib.contextmanager
def _scanner_state(rescore_age_s: float):
    """The scanner keeps one-shot guards on the CLASS. Snapshot them,
    hand the test a clean slate, and restore -- run_all shares one
    process across suites."""
    A = scanner.OptionsScannerAgent
    saved = (A._last_rescore, set(A._harvested), dict(A._short_low),
             dict(A._short_low_at), dict(A._short_step),
             set(A._long_fired), set(A._day_fired), set(A._spread_fired))
    try:
        A._last_rescore = time.time() - rescore_age_s
        for coll in (A._harvested, A._short_low, A._short_low_at,
                     A._short_step, A._long_fired, A._day_fired,
                     A._spread_fired):
            coll.clear()
        yield A
    finally:
        A._last_rescore = saved[0]
        A._harvested.clear(); A._harvested.update(saved[1])
        A._short_low.clear(); A._short_low.update(saved[2])
        A._short_low_at.clear(); A._short_low_at.update(saved[3])
        A._short_step.clear(); A._short_step.update(saved[4])
        A._long_fired.clear(); A._long_fired.update(saved[5])
        A._day_fired.clear(); A._day_fired.update(saved[6])
        A._spread_fired.clear(); A._spread_fired.update(saved[7])


# --- a recording stand-in for the supabase query-builder chain ----------

class _Query:
    def __init__(self, table: str, handler):
        self.table_name = table
        self.calls: list[tuple] = []
        self._handler = handler

    def __getattr__(self, name):
        def _chain(*args, **kwargs):
            self.calls.append((name, args))
            return self
        return _chain

    def execute(self):
        return types.SimpleNamespace(data=self._handler(self))

    def op(self, name: str) -> list:
        return [c for c in self.calls if c[0] == name]


class _Client:
    """table(name) -> a query whose execute() asks `handler(query)` for
    rows, so one client can answer the settle read (lte expiration) and
    the re-score read (gt expiration) on the same table differently."""

    def __init__(self, handler):
        self._h = handler
        self.queries: list[_Query] = []

    def table(self, name):
        q = _Query(name, self._h)
        self.queries.append(q)
        return q

    def writes(self, table: str) -> list[_Query]:
        return [q for q in self.queries
                if q.table_name == table and (q.op("update") or q.op("insert"))]


def _positions(expired=(), live=(), open_rows=()):
    def _h(q):
        if q.table_name != "options_positions":
            return []
        if q.op("lte"):
            return list(expired)
        if q.op("gt"):
            return list(live)
        if q.op("select") and not q.op("update") and not q.op("insert"):
            return list(open_rows)
        return []
    return _h


# --- shared seams --------------------------------------------------------

class _Binding:
    """Records which book is bound at the moment a broker seam is hit."""

    def __init__(self):
        self.now = None
        self.seen: list[str] = []

    @contextlib.contextmanager
    def bind_for_user(self, uid):
        prev, self.now = self.now, str(uid)
        self.seen.append(str(uid))
        try:
            yield types.SimpleNamespace(account_key=str(uid))
        finally:
            self.now = prev

    def set_account_for_user(self, uid) -> bool:
        self.now = str(uid)
        self.seen.append(str(uid))
        return True

    def clear_account(self) -> None:
        self.now = None


def _route(uid):
    if str(uid).startswith("U-unknown"):
        return False, "unknown book -- refusing rather than falling back"
    return True, "ok"


def _recorder():
    rows: list[dict] = []

    def _rec(event, ticker, *, tcs=None, strategy=None, reason="",
             iv_rank=None, extra=None):
        rows.append({"event": event, "ticker": ticker, "strategy": strategy,
                     "reason": reason, **(extra or {})})
    return rows, _rec


def _candles(n=25, close=10.0, last_volume=5000.0):
    out = []
    for i in range(n):
        out.append(types.SimpleNamespace(
            close=close, volume=(last_volume if i == n - 1 else 1000.0)))
    return out


async def _no_break():
    return 0


async def _not_halted(client, uid):
    return str(uid).startswith("U-halted")


def _occ(und, exp, cp, strike):
    return (f"{und}{exp[2:4]}{exp[5:7]}{exp[8:10]}{cp}"
            f"{int(round(strike * 1000)):08d}")


_EXP_FUTURE = (date.today() + timedelta(days=20)).isoformat()
_EXP_PAST = (date.today() - timedelta(days=1)).isoformat()


def _short_row(uid, contracts=1, rid="row-1"):
    return {"id": rid, "user_id": uid, "underlying": "AGNC",
            "strategy": "wheel_csp", "option_type": "put", "strike": 9.5,
            "contracts": contracts, "net_premium_usd": 40.0 * contracts,
            "expiration": _EXP_FUTURE,
            "legs": [{"action": "sell", "type": "put", "strike": 9.5}],
            "notes": "Placed via Alpaca"}


def _harvest_seams(rows, *, oauth_for=()):
    """Everything the re-score touches on its way to submit_option_order,
    plus recorders for what it did."""
    binding = _Binding()
    submitted: list[dict] = []
    activity, rec = _recorder()

    async def _quote(occ):
        return 0.10                       # entry 0.40 -> ratio 0.25: harvest

    async def _submit(occ_symbol, contracts, side, time_in_force="day",
                      limit_price=None, token=None):
        submitted.append({"occ": occ_symbol, "qty": contracts, "side": side,
                          "limit": limit_price, "token": token,
                          "bound": binding.now})
        return {"id": "ord-1"}, None

    async def _token(uid, broker):
        if uid in oauth_for:
            return wt.BrokerToken(access_token=f"tok-{uid}")
        return None

    async def _cnd(sym, kind):
        return _candles()

    client = _Client(_positions(live=rows))
    stack = contextlib.ExitStack()
    stack.enter_context(_patched(
        scanner, _multi_day_break=_no_break, fetch_candles_for=_cnd,
        _user_halted=_not_halted))
    stack.enter_context(_patched(alp_data, get_option_quote=_quote))
    stack.enter_context(_patched(alp, submit_option_order=_submit))
    stack.enter_context(_patched(accounts, bind_for_user=binding.bind_for_user))
    stack.enter_context(_patched(route_guard, check_route=_route))
    stack.enter_context(_patched(wt, get_user_broker_token=_token))
    stack.enter_context(_patched(act, record=rec))
    return stack, client, binding, submitted, activity


# --- TE-14 / NEQ-08: the harvest submits inside the row's own binding ----

def test_harvest_submits_inside_the_rows_own_binding_with_its_token():
    stack, client, binding, submitted, activity = _harvest_seams(
        [_short_row("U2")], oauth_for=("U2",))
    with stack, _scanner_state(rescore_age_s=7200) as A:
        out = _run(scanner.OptionsScannerAgent()._settle_expired(client))
        assert len(submitted) == 1, submitted
        s = submitted[0]
        assert s["bound"] == "U2", f"submitted under {s['bound']!r}, not the row's book"
        assert s["side"] == "buy" and s["qty"] == 1, s
        assert s["occ"] == _occ("AGNC", _EXP_FUTURE, "P", 9.5), s
        assert s["token"] is not None and s["token"].access_token == "tok-U2", (
            "the book's OAuth token must ride the order")
        assert binding.now is None, "binding leaked past the harvest"
        assert any(a["event"] == "option_harvest" and a["user_id"] == "U2"
                   for a in activity), activity
        assert any(k.startswith("h:row-1:") for k in A._harvested)
    assert not any(m.kind == "close" for m in out)


def test_harvest_without_oauth_rides_the_bound_accounts_env_keys():
    stack, client, binding, submitted, activity = _harvest_seams(
        [_short_row("U3")])
    with stack, _scanner_state(rescore_age_s=7200):
        _run(scanner.OptionsScannerAgent()._settle_expired(client))
    assert len(submitted) == 1 and submitted[0]["token"] is None, submitted
    assert submitted[0]["bound"] == "U3", submitted


def test_harvest_skips_an_unresolvable_book_and_writes_nothing():
    """Two contracts so the step-down bookkeeping WOULD run after a
    submit: with the book unresolved there must be no order, no shrink,
    no slice row, and the one-shot must stay clear for a retry."""
    stack, client, binding, submitted, activity = _harvest_seams(
        [_short_row("U-unknown-9", contracts=2)])
    with stack, _scanner_state(rescore_age_s=7200) as A:
        _run(scanner.OptionsScannerAgent()._settle_expired(client))
        assert submitted == [], "an unresolved book must never reach the broker"
        assert client.writes("options_positions") == [], "bookkeeping ran without an order"
        assert any(a["event"] == "route_mismatch" for a in activity), activity
        assert not A._harvested, "a skipped row must be retried next hour"
    assert "U-unknown-9" in binding.seen, "the row's book was never bound"


def test_harvest_skips_a_halted_book_and_says_so():
    stack, client, binding, submitted, activity = _harvest_seams(
        [_short_row("U-halted-1", contracts=2)])
    with stack, _scanner_state(rescore_age_s=7200) as A:
        _run(scanner.OptionsScannerAgent()._settle_expired(client))
        assert submitted == []
        assert client.writes("options_positions") == []
        assert any(a["event"] == "option_harvest_skip"
                   and a["user_id"] == "U-halted-1" for a in activity), activity
        assert not A._harvested


def test_step_down_bookkeeping_runs_only_after_a_bound_accepted_order():
    """Two contracts, ratio 0.25 -> step-out of 1 of 2. The shrink and the
    closed_partial slice follow ONLY the accepted, bound submit."""
    stack, client, binding, submitted, activity = _harvest_seams(
        [_short_row("U2", contracts=2)])
    with stack, _scanner_state(rescore_age_s=7200):
        _run(scanner.OptionsScannerAgent()._settle_expired(client))
    assert len(submitted) == 1 and submitted[0]["qty"] == 1, submitted
    assert submitted[0]["bound"] == "U2"
    writes = client.writes("options_positions")
    ups = [q for q in writes if q.op("update")]
    ins = [q for q in writes if q.op("insert")]
    assert ups and ups[0].op("update")[0][1][0]["contracts"] == 1, ups
    assert ins and ins[0].op("insert")[0][1][0]["status"] == "closed_partial", ins
    assert ins[0].op("insert")[0][1][0]["user_id"] == "U2"


# --- TE-15: reconcile is bound per book and honours a strict None -------

def _reconcile_seams(open_rows, *, strict, fills=None):
    binding = _Binding()
    activity, rec = _recorder()
    reads: list[dict] = []

    async def _strict(token=None):
        reads.append({"what": "positions", "bound": binding.now})
        return strict

    async def _closed(symbol, token=None, limit=8):
        reads.append({"what": "orders", "bound": binding.now, "symbol": symbol})
        return list(fills or [])

    async def _token(uid, broker):
        return None

    client = _Client(_positions(open_rows=open_rows))
    stack = contextlib.ExitStack()
    stack.enter_context(_patched(scanner, _primary_book=lambda: ""))
    stack.enter_context(_patched(
        alp, get_option_positions_strict=_strict,
        get_recent_closed_orders=_closed, alpaca_configured=lambda: True))
    stack.enter_context(_patched(
        accounts, set_account_for_user=binding.set_account_for_user,
        clear_account=binding.clear_account))
    stack.enter_context(_patched(route_guard, check_route=_route))
    stack.enter_context(_patched(wt, get_user_broker_token=_token))
    stack.enter_context(_patched(act, record=rec))
    return stack, client, binding, reads, activity


def test_reconcile_continues_on_a_none_strict_read_and_closes_nothing():
    stack, client, binding, reads, activity = _reconcile_seams(
        [_short_row("U2")], strict=None)
    with stack:
        out = _run(scanner.OptionsScannerAgent()._reconcile_with_broker(client))
    assert client.writes("options_positions") == [], "closed on an answerless read"
    assert out == [], out
    assert reads and reads[0]["bound"] == "U2", reads
    assert any(a["event"] == "reconcile_skipped_unreadable"
               and a["user_id"] == "U2" for a in activity), activity
    assert binding.now is None, "reconcile must clear its binding"


def test_reconcile_reads_the_broker_under_each_rows_own_book():
    rows = [_short_row("U2", rid="r2"), _short_row("U3", rid="r3")]
    occ = _occ("AGNC", _EXP_FUTURE, "P", 9.5)
    stack, client, binding, reads, activity = _reconcile_seams(
        rows, strict=[{"symbol": occ, "qty": "-1", "avg_entry_price": "0.4"}])
    with stack:
        _run(scanner.OptionsScannerAgent()._reconcile_with_broker(client))
    assert [r["bound"] for r in reads if r["what"] == "positions"] == ["U2", "U3"], reads
    assert client.writes("options_positions") == [], "matched rows must stay open"


def test_reconcile_skips_an_unresolvable_book_entirely():
    stack, client, binding, reads, activity = _reconcile_seams(
        [_short_row("U-unknown-7")], strict=[])
    with stack:
        _run(scanner.OptionsScannerAgent()._reconcile_with_broker(client))
    assert reads == [], "an unresolved book must never reach the broker"
    assert client.writes("options_positions") == []
    assert any(a["event"] == "route_mismatch" for a in activity), activity


def test_reconcile_holds_a_row_when_the_broker_is_flat_and_no_fill_exists():
    stack, client, binding, reads, activity = _reconcile_seams(
        [_short_row("U2")], strict=[], fills=[])
    with stack:
        _run(scanner.OptionsScannerAgent()._reconcile_with_broker(client))
    assert client.writes("options_positions") == []
    assert any(a["event"] == "reconcile_hold" for a in activity), activity
    assert [r["bound"] for r in reads if r["what"] == "orders"] == ["U2"], reads


def test_reconcile_books_the_true_exit_from_the_books_own_fill():
    """credit 40, bought back at 0.20 x 100 -> realized +20. Before this
    audit the select never fetched net_premium_usd, so this booked -20."""
    stack, client, binding, reads, activity = _reconcile_seams(
        [_short_row("U2")], strict=[],
        fills=[{"status": "filled", "filled_avg_price": "0.20", "side": "buy"}])
    with stack:
        out = _run(scanner.OptionsScannerAgent()._reconcile_with_broker(client))
    ups = [q for q in client.writes("options_positions") if q.op("update")]
    assert len(ups) == 1, ups
    body = ups[0].op("update")[0][1][0]
    assert body["status"] == "closed_manual" and body["realized_pnl_usd"] == 20.0, body
    assert out and out[0].payload["closed_count"] == 1


def test_reconcile_adopts_a_broker_contract_into_the_bound_book():
    exp = _EXP_FUTURE
    stack, client, binding, reads, activity = _reconcile_seams(
        [_short_row("U3")],
        strict=[{"symbol": _occ("AGNC", exp, "P", 9.5), "qty": "-1",
                 "avg_entry_price": "0.4"},
                {"symbol": _occ("F", exp, "P", 12.5), "qty": "-1",
                 "avg_entry_price": "0.3"}])
    with stack:
        _run(scanner.OptionsScannerAgent()._reconcile_with_broker(client))
    ins = [q for q in client.writes("options_positions") if q.op("insert")]
    assert len(ins) == 1, ins
    body = ins[0].op("insert")[0][1][0]
    assert body["user_id"] == "U3" and body["underlying"] == "F", body


# --- NEQ-10: settle defers when there is no price ------------------------

def _expired_csp(uid="U1"):
    return {"id": "row-x", "user_id": uid, "underlying": "F",
            "strategy": "wheel_csp", "option_type": "put", "strike": 12.5,
            "contracts": 1, "net_premium_usd": 30.0, "expiration": _EXP_PAST}


def _settle(client, candles):
    activity, rec = _recorder()

    async def _cnd(sym, kind):
        if isinstance(candles, Exception):
            raise candles
        return candles
    with _patched(scanner, fetch_candles_for=_cnd), _patched(act, record=rec), \
            _scanner_state(rescore_age_s=0):
        out = _run(scanner.OptionsScannerAgent()._settle_expired(client))
    return out, activity


def test_settle_defers_when_no_candles_and_writes_nothing():
    client = _Client(_positions(expired=[_expired_csp()]))
    out, activity = _settle(client, [])
    assert client.writes("options_positions") == [], "settled with no price"
    assert out == [], out
    assert any(a["event"] == "settle_deferred_no_price" and a["user_id"] == "U1"
               for a in activity), activity


def test_settle_defers_when_the_price_read_raises():
    client = _Client(_positions(expired=[_expired_csp()]))
    out, activity = _settle(client, RuntimeError("data feed down"))
    assert client.writes("options_positions") == []
    assert any(a["event"] == "settle_deferred_no_price" for a in activity)


def test_settle_still_books_a_priced_expiry_correctly():
    client = _Client(_positions(expired=[_expired_csp()]))
    out, _ = _settle(client, _candles(close=13.0))
    body = client.writes("options_positions")[0].op("update")[0][1][0]
    assert body["status"] == "closed_expired" and body["realized_pnl_usd"] == 30.0, body
    assert out and out[0].payload["status"] == "closed_expired"

    client = _Client(_positions(expired=[_expired_csp()]))
    out, _ = _settle(client, _candles(close=12.0))
    body = client.writes("options_positions")[0].op("update")[0][1][0]
    assert body["status"] == "closed_assigned" and body["realized_pnl_usd"] == -20.0, body


# --- KS-6: the fire-block verdict ---------------------------------------

def test_fire_block_reason_fails_closed_on_unreadable_states():
    r = scanner._fire_block_reason(None, "U1", "wheel_csp")
    assert r and "unreadable" in r, r


def test_fire_block_reason_matches_the_fanouts_verdicts():
    halted = ks.KillSwitch(True, "day", "Daily loss limit", mode="halt")
    recovering = ks.KillSwitch(False, "week", "Weekly loss limit", mode="recovery")
    clean = ks.KillSwitch(False, None, None)
    states = {"H": halted, "R": recovering, "C": clean}
    assert "halted" in (scanner._fire_block_reason(states, "H", "wheel_csp") or "")
    assert "suspends option_day" in (scanner._fire_block_reason(states, "R", "option_day") or "")
    assert "suspends long_put" in (scanner._fire_block_reason(states, "R", "long_put") or "")
    assert scanner._fire_block_reason(states, "R", "wheel_csp") is None, "wheel tightens, never suspends"
    assert scanner._fire_block_reason(states, "R", "bull_put_spread") is None
    assert scanner._fire_block_reason(states, "C", "option_day") is None
    assert scanner._fire_block_reason(states, "nobody", "option_day") is None


# --- KS-6, driven: a recovering book's suspended lane does not fire ------

def _directional_seams(states):
    binding = _Binding()
    activity, rec = _recorder()

    async def _states(client):
        return states

    async def _acct(token=None):
        return types.SimpleNamespace(equity=10_000.0, options_approved_level=3)

    async def _cnd(sym, kind):
        return _candles(close=100.0)

    async def _never_pick(*a, **k):
        raise AssertionError("live_option_pick reached for a suspended lane")

    async def _never_submit(*a, **k):
        raise AssertionError("submit_option_order reached for a suspended lane")

    stack = contextlib.ExitStack()
    stack.enter_context(_patched(
        scanner, _lane_enabled=lambda name: True, _primary_book=lambda: "U1",
        fetch_candles_for=_cnd, _user_halted=_not_halted))
    stack.enter_context(_patched(ks, check_states=_states))
    stack.enter_context(_patched(
        alp, alpaca_configured=lambda: True, get_account=_acct,
        submit_option_order=_never_submit))
    stack.enter_context(_patched(alp_data, live_option_pick=_never_pick))
    stack.enter_context(_patched(accounts, bind_for_user=binding.bind_for_user))
    stack.enter_context(_patched(route_guard, check_route=_route))
    stack.enter_context(_patched(act, record=rec))
    return stack, binding, activity


@contextlib.contextmanager
def _generals(gens):
    saved = mu.SECTOR_BIAS.get("generals")
    mu.SECTOR_BIAS["generals"] = gens
    try:
        yield
    finally:
        mu.SECTOR_BIAS["generals"] = saved


def test_a_recovering_books_directional_lane_does_not_fire():
    states = {"U1": ks.KillSwitch(False, "week", "Weekly loss limit -6%",
                                  mode="recovery")}
    stack, binding, activity = _directional_seams(states)
    with stack, _generals([{"sym": "NVDA", "d3": 4.0}]), \
            _scanner_state(rescore_age_s=0) as A:
        out = _run(scanner.OptionsScannerAgent()._run_directional(_Client(_positions())))
        assert out == [], out
        assert not A._long_fired, "a skipped name must not burn its one-shot"
    skips = [a for a in activity if a["event"] == "option_long_skip"]
    assert skips and "recovery suspends long_call" in skips[0]["reason"], activity
    assert skips[0]["user_id"] == "U1"
    assert binding.seen == ["U1"], "the lane body must run bound to the primary book"


def test_an_unreadable_kill_switch_stands_the_directional_lane_down():
    stack, binding, activity = _directional_seams(None)
    with stack, _generals([{"sym": "NVDA", "d3": 4.0}]), _scanner_state(0):
        out = _run(scanner.OptionsScannerAgent()._run_directional(_Client(_positions())))
    assert out == []
    assert any(a["event"] == "option_long_skip" and "unreadable" in a["reason"]
               for a in activity), activity


def test_a_clean_book_still_reaches_the_live_pick():
    """The KS-6 gate must not silently kill the lane: with a clean state
    the lane proceeds to the live contract pick (stubbed to stop it)."""
    states = {"U1": ks.KillSwitch(False, None, None)}
    stack, binding, activity = _directional_seams(states)
    reached = {"pick": 0}

    async def _pick(*a, **k):
        reached["pick"] += 1
        return None                       # no contract -> lane moves on
    with stack, _patched(alp_data, live_option_pick=_pick), \
            _generals([{"sym": "NVDA", "d3": 4.0}]), _scanner_state(0):
        _run(scanner.OptionsScannerAgent()._run_directional(_Client(_positions())))
    assert reached["pick"] == 1, "a clean book never got as far as the pick"
    assert not [a for a in activity if a["event"] == "option_long_skip"]


# --- NEQ-09: lane switches and the primary book ---------------------------

def test_lanes_are_off_by_default_and_never_touch_the_book():
    """No Settings field, no env var -> the switch is False and the lane
    returns before it resolves a book or binds anything."""
    for name in ("TREZO_DAY_OPTIONS", "TREZO_SPREADS", "TREZO_LONG_OPTIONS"):
        assert os.getenv(name) is None, f"{name} set in this shell; test env is dirty"
        assert scanner._lane_enabled(name) is False

    def _boom():
        raise AssertionError("_primary_book reached with the lane off")
    a = scanner.OptionsScannerAgent()
    with _patched(scanner, _primary_book=_boom):
        for fn in (a._run_same_day, a._run_spreads, a._run_directional):
            assert _run(fn(_Client(_positions()))) == []


def test_lane_switch_reads_settings_first_then_the_process_env():
    with _patched(scanner, get_settings=lambda: types.SimpleNamespace(trezo_day_options=True)):
        assert scanner._lane_enabled("TREZO_DAY_OPTIONS") is True
    with _patched(scanner, get_settings=lambda: types.SimpleNamespace(trezo_day_options="0")):
        assert scanner._lane_enabled("TREZO_DAY_OPTIONS") is False
    assert os.getenv("TREZO_SPREADS") is None
    os.environ["TREZO_SPREADS"] = "1"
    try:
        with _patched(scanner, get_settings=lambda: types.SimpleNamespace()):
            assert scanner._lane_enabled("TREZO_SPREADS") is True
    finally:
        del os.environ["TREZO_SPREADS"]
    assert scanner._lane_enabled("TREZO_SPREADS") is False


def test_lane_bodies_run_only_inside_a_verified_binding():
    """_run_bound: an unresolvable primary is refused with a route
    mismatch and the lane body is never entered."""
    activity, rec = _recorder()
    binding = _Binding()

    async def _never(self, client, uid):
        raise AssertionError("lane body entered for an unresolved book")
    a = scanner.OptionsScannerAgent()
    with _patched(scanner, _lane_enabled=lambda n: True,
                  _primary_book=lambda: "U-unknown-1"), \
            _patched(scanner.OptionsScannerAgent, _run_same_day_for=_never,
                     _run_spreads_for=_never, _run_directional_for=_never), \
            _patched(accounts, bind_for_user=binding.bind_for_user), \
            _patched(route_guard, check_route=_route), _patched(act, record=rec):
        for fn in (a._run_same_day, a._run_spreads, a._run_directional):
            assert _run(fn(_Client(_positions()))) == []
    assert len([x for x in activity if x["event"] == "route_mismatch"]) == 3, activity
    assert binding.now is None


def test_primary_book_comes_from_runtime_settings_not_os_getenv():
    rs = load_module("app.runtime.settings")
    with _patched(rs, primary_user_id=lambda: "book-from-settings"):
        assert scanner._primary_book() == "book-from-settings"
    src = (Path(__file__).resolve().parents[1]
           / "app" / "agents" / "options_scanner.py").read_text(encoding="utf-8")
    assert 'getenv("TREZO_PRIMARY_USER_ID"' not in src, "a bare os.getenv read of the primary id came back"
    for name in ("TREZO_DAY_OPTIONS", "TREZO_SPREADS", "TREZO_LONG_OPTIONS"):
        assert f'getenv("{name}"' not in src, f"{name} is read with os.getenv again"


# --- the wheel auto-fire tracking row: `client` is finally in scope -------

def test_wheel_auto_fire_tracking_insert_can_see_its_client():
    """The insert closure used to look `client` up as a GLOBAL that did not
    exist, so every auto-fired leg raised NameError after the order was
    accepted. Now it is a parameter, and both call sites pass it."""
    fn = scanner.OptionsScannerAgent._wheel_auto_fire
    assert "client" in fn.__code__.co_varnames
    inner = [c for c in fn.__code__.co_consts
             if isinstance(c, types.CodeType) and c.co_name == "_sync_insert"]
    assert inner and "client" in inner[0].co_freevars, (
        "the tracking insert still resolves `client` as a global")
    src = (Path(__file__).resolve().parents[1]
           / "app" / "agents" / "options_scanner.py").read_text(encoding="utf-8")
    body = src[src.index("async def _run_cc_overlay"):]
    assert body.count("self._wheel_auto_fire(") == 2, "call-site count changed; re-check"
    for i in range(2):
        j = body.index("self._wheel_auto_fire(")
        assert "client=client" in body[j:j + 400], "a call site does not pass client"
        body = body[j + 10:]


if __name__ == "__main__":
    sys.exit(run_tests(dict(vars())))
