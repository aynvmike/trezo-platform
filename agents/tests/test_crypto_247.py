"""The crypto lane defends a LOSING coin 24/7 (Mike 2026-09-02, the DOT bleed).

DOT on the 75k (2026-08-24 -> 09-02, -$1,138): the lane already ran
around the clock on every book -- scanner with no calendar gate, Risk
Manager skipping the equity filter for coins, execution never reading the
market clock, the monitor's crypto branch checking stop/target every 60s.
What nothing did was ACT on a coin simply losing between a far stop and
its target: the ladder and both trails only raise a winner's stop, the
intraday time stops are stock-only by Mike's 2026-08-05 decision, the
exit advisor acts on winners, and the reevaluator was never reached by a
broker-routed row (the Alpaca block `continue`s before its call -- and
with every open row broker-routed, it was dead platform-wide).

What this suite pins:
  * asset_policy.crypto_stale_exit_for: the per-strategy MAE ceiling and
    losing-time limit (swing 4d/8%, scalp 1d/5%, dca 7d/10%, hodl none,
    adopted/unnamed -> the swing limits).
  * position_monitor._decide_crypto_stale_exit: pure, never raises, never
    judges a winner, HODL exempt, adopted rows only SAID (adopted_underwater)
    until TREZO_CRYPTO_MAE_ADOPTED, the time limit only with
    TREZO_CRYPTO_TIME_EXIT, both measured from the row's own entry_at.
  * The REAL tick, crypto branch, on a closed equity market: the new
    reasons flow into the EXISTING per-book _throttled_liquidate ->
    close_position path, every activity row names the book, the
    reevaluator call (behind TREZO_CRYPTO_REEVAL) passes target=None and
    only ratchets a returned stop UP, and an OFF flag is said hourly.
  * Two latent NameErrors fixed on the way: the ladder's
    "breached rung" block lived in _maybe_trail_hodl where none of its
    names exist; and the ladder's record() calls passed kwargs record()
    does not accept.
  * Source pins: the crypto path has no session gate (crypto_scanner,
    _execute_alpaca_crypto), the 5-liquidate / 3-resync / SELECT-tail
    contracts test_monitor_bookbound relies on are intact, peak_price is
    NOT in the tick SELECT (binding it flips the reevaluator's giveback
    rule for every once-green loser -- a fleet decision, not this track's).

Contract: plain zero-arg test_ functions, _bootstrap.stub_config() +
load_module, patch-and-restore, activity_log.record captured in every
real-tick test so nothing reaches the live log. No pytest, no .env, no
network.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _bootstrap import load_module, run_tests, stub_config  # noqa: E402

stub_config()
# app.runtime must be stubbed BEFORE position_monitor imports
# app.runtime.asset_policy, or the real package __init__ boots the bus.
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
reeval = load_module("app.agents.reevaluator")
pm = load_module("app.agents.position_monitor")
ops_watchdog = load_module("app.agents.ops_watchdog")
options_scanner = load_module("app.agents.options_scanner")

AGENTS_DIR = Path(__file__).resolve().parents[1]
PM_SRC = (AGENTS_DIR / "app/agents/position_monitor.py").read_text(
    encoding="utf-8", errors="replace")


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
    """Pin the account registry for ONE test (same pattern as
    test_monitor_bookbound: the accounts module, route_guard, and the
    copy position_monitor bound at import)."""
    by_key = {b.account_key: b for b in books}
    multi = len(books) > 1

    def _for_user(uid):
        return by_key.get(str(uid or ""))

    def _skip(uid):
        return multi and _for_user(uid) is None

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


# --- a Supabase double just deep enough --------------------------------

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


def _ago(**kw) -> str:
    return (datetime.now(timezone.utc) - timedelta(**kw)).isoformat()


def _crypto_row(uid, **over):
    """A losing long DOT swing on the 25k, broker-routed, 5 days old, with
    the far stop that let DOT bleed: entry 1.0, stop 0.85, target 1.12."""
    r = {"id": f"pos-{uid}-DOT", "user_id": uid, "ticker": "DOT",
         "asset_type": "crypto", "side": "long", "quantity": 100.0,
         "entry_price": 1.0, "stop_price": 0.85, "target_price": 1.12,
         "strategy": "crypto_swing", "entry_at": _ago(days=5),
         "broker": "alpaca", "close_requested": False,
         "source_payload": None}
    r.update(over)
    return r


class _Seen:
    """What the real tick did, with the book that was bound when it did it."""

    def __init__(self):
        self.liq: list = []          # (symbol, asset_type, user_id, bound)
        self.closes: list = []       # (user_id, pid, reason)
        self.tp: list = []           # targets handed to _push_crypto_tp
        self.reeval: list = []       # kwargs the reevaluate_position stub saw
        self.said: list = []         # (event, TICKER, kwargs) activity rows

    def events(self, name=None):
        return [(e, t, k) for e, t, k in self.said if name is None or e == name]


@contextlib.contextmanager
def _real_tick(client, price, seen: _Seen, **extra):
    """Drive the REAL PositionMonitorAgent.tick() with only the external
    seams swapped. Sunday 03:00: the equity session is CLOSED
    (ops_watchdog._us_market_open -> False) -- if any crypto exit needed
    the session, these tests would see nothing fire. The broker holds
    the coin for the row's book (DOTUSD), the liquidate and the ledger
    close are captured with the book bound at the time, and every
    activity row is captured instead of written."""
    async def _price(tk, at):
        return price

    async def _noop(*_a, **_k):
        return None

    async def _nolock(user_id):
        return None

    async def _nostep(*_a, **_k):
        return False, 0

    async def _held(user_id, *, where="", max_age_s=None):
        return {"DOTUSD", "AMZN"}

    async def _liq(symbol, asset_type="stock", user_id=None):
        seen.liq.append((symbol, asset_type, user_id, _bound_id()))
        return object(), "ok"

    async def _close(user_id, pid, exit_price, reason="stop"):
        seen.closes.append((user_id, pid, reason))
        return engine.FillResult(ok=True, position_id=pid,
                                 fill_price=exit_price, realized_pnl_usd=-1.0)

    async def _tp(r, target):
        seen.tp.append(target)

    def _rec(event, ticker="", *_a, **kw):
        seen.said.append((str(event), str(ticker or "").upper(), kw))

    async def _no_reeval(*_a, **_k):
        raise AssertionError("reevaluate_position must not be reached here")

    saved = (pm.PositionMonitorAgent._recon_tick_counter,
             pm.PositionMonitorAgent._did_initial_reconcile)
    pm.PositionMonitorAgent._recon_tick_counter = 0
    pm.PositionMonitorAgent._did_initial_reconcile = True
    throttles = (dict(pm._crypto_reeval_off_at), dict(pm._adopted_underwater_at))
    pm._crypto_reeval_off_at.clear()
    pm._adopted_underwater_at.clear()
    defaults = dict(
        _supabase=lambda: client, _latest_price=_price,
        _manage_day_options=_noop, _gap_check_open_bell=_noop,
        _pre_break_review=_noop, check_and_lock_profit=_nolock,
        _step_check=_nostep,
        _throttled_liquidate=_liq, close_position=_close,
        _arm_broker_stop=_noop, _push_crypto_tp=_tp,
        _maybe_ladder_stop=_noop, _maybe_trail_stock_profit=_noop,
        _maybe_trail_hodl=_noop,
        # defaults for the switches: reeval gated OFF, time rule OFF,
        # adopted MAE OFF -- exactly what ships; tests flip per case.
        reeval_is_enabled=lambda: True, reevaluate_position=_no_reeval,
        _crypto_reeval_enabled=lambda: False,
        _crypto_time_exit_enabled=lambda: False,
        _crypto_mae_adopted_enabled=lambda: False,
    )
    defaults.update(extra)
    try:
        with _patched(pm, **defaults), \
                _patched(book_scope, held_symbols=_held), \
                _patched(ops_watchdog, _us_market_open=lambda: False), \
                _patched(alog, record=_rec):
            yield
    finally:
        (pm.PositionMonitorAgent._recon_tick_counter,
         pm.PositionMonitorAgent._did_initial_reconcile) = saved
        pm._crypto_reeval_off_at.clear()
        pm._crypto_reeval_off_at.update(throttles[0])
        pm._adopted_underwater_at.clear()
        pm._adopted_underwater_at.update(throttles[1])
        accounts.clear_account()


# =======================================================================
# 1. the policy table
# =======================================================================

def test_crypto_policy_values():
    pol = ap.policy_for("crypto")
    assert pol.session_gated is False and pol.native_brackets is False
    assert ap.crypto_stale_exit_for("crypto_swing").limits == (4.0, 0.08)
    assert ap.crypto_stale_exit_for("swing").limits == (4.0, 0.08)
    assert ap.crypto_stale_exit_for("crypto_scalp").limits == (1.0, 0.05)
    assert ap.crypto_stale_exit_for("crypto_dca").limits == (7.0, 0.10)
    assert ap.crypto_stale_exit_for("crypto_hodl").limits == (None, None)
    for unnamed in ("adopted_crypto", "", None, "reconciled_import"):
        assert ap.crypto_stale_exit_for(unnamed).limits == (4.0, 0.08), unnamed
    assert ap.crypto_stale_exit_for("adopted_crypto").mode == "default"
    # the registry itself is unchanged: no new asset_type literal
    assert ap.registered_types() == sorted(
        ["stock", "crypto", "option", "forex", "future", "bond", "fund", "cash"])


# =======================================================================
# 2. source pins: no session gate anywhere on the crypto path; the
#    contracts other suites rely on survive; the new code is WIRED
# =======================================================================

def test_crypto_path_has_no_session_gate_source_pins():
    # crypto_scanner: no calendar gate of any kind
    sc = (AGENTS_DIR / "app/agents/crypto_scanner.py").read_text(
        encoding="utf-8", errors="replace")
    for gate in ("_us_market_open", "weekday(", "get_clock", "is_open"):
        assert gate not in sc, f"crypto_scanner grew a session gate: {gate}"
    # trade_execution._execute_alpaca_crypto: no clock read in the BODY
    # (the docstring says the word 'clock' on purpose -- slice the code)
    te = (AGENTS_DIR / "app/agents/trade_execution.py").read_text(
        encoding="utf-8", errors="replace")
    start = te.index("async def _execute_alpaca_crypto")
    nxt = te.find("\n    async def ", start + 10)
    body = te[start:nxt if nxt > 0 else len(te)]
    assert "get_clock" not in body, "_execute_alpaca_crypto now reads the clock"
    # position_monitor: the crypto branch calls the reevaluator (anchored
    # on reeval_close_c) AND the internal line other suites pin is intact
    assert "reeval_close_c" in PM_SRC
    assert PM_SRC.count("if reeval_is_enabled() and not _nps:") == 1
    assert PM_SRC.count("await reevaluate_position(") == 2, \
        "expected the internal call plus the crypto-branch call"
    # target=None on the crypto call: lower_target must never touch a coin
    i = PM_SRC.index("reeval_close_c = None")
    crypto_call = PM_SRC[i:PM_SRC.index("# Scalp net-edge auto-exit", i)]
    assert re.search(r"stop_c,\s*None,\s*\n\s*emit=out", crypto_call), \
        "the crypto reevaluate_position call must pass target=None"
    # the exits flow into the EXISTING per-book liquidate: still 5 sites
    calls = re.findall(r"await _throttled_liquidate\(", PM_SRC)
    assert len(calls) == 5, f"liquidate call sites: {len(calls)} (expected 5)"
    assert PM_SRC.count("await resync_alpaca_legs(") == 3
    # the tick SELECT is unchanged: its tail, and NO peak_price binding
    assert 'close_requested, source_payload")' in PM_SRC
    sel = [ln for ln in PM_SRC.splitlines()
           if ".select(" in ln and 'close_requested, source_payload")' in ln]
    assert len(sel) == 1, sel
    assert "peak_price" not in sel[0], (
        "peak_price in the tick SELECT flips the reevaluator giveback rule "
        "for every once-green loser and the stock ladder anchor -- a fleet "
        "decision, not this track's (skeptic 2026-09-02)")
    # every new activity row is a LATE import, so a patched record reaches it
    for ev in ("crypto_reeval", "crypto_reeval_off", "adopted_underwater",
               "_cexit_event, tk"):
        assert ev in PM_SRC, ev
    assert not re.search(r"^from app\.agents\.activity_log import record",
                         PM_SRC, re.M), "record must not be bound at module level"
    # the latent NameError is gone: the breached block lives in the ladder
    hodl_src = inspect.getsource(pm._maybe_trail_hodl)
    ladder_src = inspect.getsource(pm._maybe_ladder_stop)
    assert "_breached" not in hodl_src and "record(" not in hodl_src
    assert "if _breached:" in ladder_src and "ladder_lock_breached" in ladder_src
    # record()'s real signature is honoured (no bare kwargs)
    assert not re.search(r"record\(\"ladder_lock_[a-z_]+\", tk,\s*\n\s*entry=",
                         ladder_src), "record() takes no bare entry= kwarg"
    # the 2026-08-05 exemption in _decide_time_stop is untouched
    assert 'DO NOT "fix" this by adding a crypto_ prefix here' in PM_SRC
    assert pm._decide_time_stop(
        {"strategy": "crypto_swing", "entry_at": _ago(hours=3)},
        "long", 1.0, 0.9) == (None, "")


# =======================================================================
# 3. the pure function
# =======================================================================

def test_decide_crypto_stale_exit_pure_function():
    d = pm._decide_crypto_stale_exit
    time_off = {"_crypto_time_exit_enabled": lambda: False}
    time_on = {"_crypto_time_exit_enabled": lambda: True}
    adopted_off = {"_crypto_mae_adopted_enabled": lambda: False}
    dot = {"asset_type": "crypto", "side": "long", "strategy": "crypto_swing",
           "entry_price": 0.925859, "stop_price": 0.799997,
           "target_price": 0.999928, "entry_at": _ago(hours=6)}
    with _patched(pm, **time_off, **adopted_off):
        # the DOT geometry: -8.9% vs the 8% swing ceiling -> stop, now
        reason, detail = d(dot, 0.8431)
        assert reason == "stop" and detail.startswith("crypto_mae_exit:"), (reason, detail)
        assert "8.9%" in detail and "ceiling 8%" in detail and "0.799997" in detail
        # the same coin ADOPTED: said, not sold
        reason, detail = d({**dot, "source_payload": {"adopted": True}}, 0.8431)
        assert reason is None and detail.startswith("adopted_underwater:"), (reason, detail)
        reason, detail = d({**dot, "strategy": "adopted_crypto"}, 0.8431)
        assert reason is None and detail.startswith("adopted_underwater:")
        # a JSON-string payload is read too
        reason, detail = d({**dot, "source_payload": '{"adopted": true}'}, 0.8431)
        assert reason is None and detail.startswith("adopted_underwater:")
        # -5%: under the ceiling, time rule off -> nothing, even at 9 days
        assert d({**dot, "entry_at": _ago(days=9)}, 0.8796) == (None, "")
        # winners, flat, HODL, shorts, stocks: never judged
        assert d({**dot, "entry_at": _ago(days=30)}, 0.95) == (None, "")
        assert d({**dot, "entry_at": _ago(days=30)}, 0.925859) == (None, "")
        assert d({**dot, "strategy": "crypto_hodl", "entry_at": _ago(days=30)},
                 0.70) == (None, "")
        assert d({**dot, "side": "short"}, 0.5) == (None, "")
        assert d({**dot, "asset_type": "stock"}, 0.5) == (None, "")
        # fail-safe on bad numbers: a None/0 entry or price must NOT raise
        for bad in ({**dot, "entry_price": None}, {**dot, "entry_price": 0},
                    {**dot, "entry_price": "abc"}):
            assert d(bad, 0.5) == (None, "")
        assert d(dot, 0) == (None, "") and d(dot, None) == (None, "")
        # scalp: 5% ceiling
        assert d({**dot, "strategy": "crypto_scalp"}, 0.925859 * 0.94)[0] == "stop"
        assert d({**dot, "strategy": "crypto_scalp"}, 0.925859 * 0.96) == (None, "")
    with _patched(pm, **time_on, **adopted_off):
        # time rule ON: 5d at -6% -> time; the clock is the row's entry_at
        reason, detail = d({**dot, "entry_at": _ago(days=5)}, 0.87)
        assert reason == "time" and detail.startswith("crypto_time_exit:"), (reason, detail)
        assert ">= 4d" in detail and "clock: row entry_at" in detail
        # ... and 3.9d is not 4d; a missing entry_at is 0d (no exit)
        assert d({**dot, "entry_at": _ago(days=3, hours=20)}, 0.87) == (None, "")
        assert d({**dot, "entry_at": None}, 0.87) == (None, "")
        # adopted row under the ceiling AND past the time limit: the time
        # rule still fires (its clock = adoption time, said in the detail)
        reason, detail = d({**dot, "strategy": "adopted_crypto",
                            "entry_at": _ago(days=5)}, 0.8431)
        assert reason == "time" and "= adoption time" in detail
        # scalp: a day; dca: a week; hodl: never
        assert d({**dot, "strategy": "crypto_scalp", "entry_at": _ago(days=1, hours=1)},
                 0.91)[0] == "time"
        assert d({**dot, "strategy": "crypto_dca", "entry_at": _ago(days=6)},
                 0.91) == (None, "")
        assert d({**dot, "strategy": "crypto_dca", "entry_at": _ago(days=7, hours=1)},
                 0.91)[0] == "time"
        assert d({**dot, "strategy": "crypto_hodl", "entry_at": _ago(days=90)},
                 0.60) == (None, "")
    with _patched(pm, **time_off, _crypto_mae_adopted_enabled=lambda: True):
        reason, detail = d({**dot, "source_payload": {"adopted": True}}, 0.8431)
        assert reason == "stop" and "[adopted row, TREZO_CRYPTO_MAE_ADOPTED=1]" in detail


def test_the_switches_default_off_and_read_the_env_per_call():
    import os
    for env, fn in (("TREZO_CRYPTO_TIME_EXIT", pm._crypto_time_exit_enabled),
                    ("TREZO_CRYPTO_MAE_ADOPTED", pm._crypto_mae_adopted_enabled),
                    ("TREZO_CRYPTO_REEVAL", pm._crypto_reeval_enabled)):
        had = os.environ.pop(env, None)
        try:
            assert fn() is False, f"{env} must default OFF"
            os.environ[env] = "1"
            assert fn() is True
            os.environ[env] = "off"
            assert fn() is False
        finally:
            if had is None:
                os.environ.pop(env, None)
            else:
                os.environ[env] = had


# =======================================================================
# 4. the REAL tick: exits flow into the existing per-book path
# =======================================================================

def test_stale_losing_swing_is_closed_by_the_time_rule_on_a_closed_market():
    row = _crypto_row("book-b", entry_at=_ago(days=5))
    client = _Client({"paper_positions": [row]})
    seen = _Seen()
    agent = pm.PositionMonitorAgent()
    with _registry(_two_books()), \
            _real_tick(client, 0.94, seen, _crypto_time_exit_enabled=lambda: True):
        out = _run(agent.tick())
    assert seen.liq == [("DOT", "crypto", "book-b", "acct2")], seen.liq
    assert seen.closes == [("book-b", "pos-book-b-DOT", "time")], seen.closes
    rows = seen.events("crypto_time_exit")
    assert len(rows) == 1 and rows[0][1] == "DOT", seen.said
    assert rows[0][2]["extra"]["user_id"] == "book-b"
    assert rows[0][2]["reason"].startswith("crypto_time_exit: losing 6.0%")
    closes = [m for m in out if m.kind == "close"]
    assert len(closes) == 1 and closes[0].payload["reason"] == "time"
    assert closes[0].payload["detail"].startswith("crypto_time_exit")
    assert closes[0].payload["user_id"] == "book-b"


def test_the_time_rule_is_off_by_default_and_the_row_rides():
    """Mike's 2026-08-05 note stands until he says otherwise: with the
    switch at its default, the same 5-day loser is held (and the venue
    stop is re-armed as before)."""
    row = _crypto_row("book-b", entry_at=_ago(days=5))
    client = _Client({"paper_positions": [row]})
    seen = _Seen()
    armed = []

    async def _arm(r):
        armed.append(r.get("user_id"))

    agent = pm.PositionMonitorAgent()
    with _registry(_two_books()), _real_tick(client, 0.94, seen, _arm_broker_stop=_arm):
        out = _run(agent.tick())
    assert seen.liq == [] and seen.closes == [], (seen.liq, seen.closes)
    assert armed == ["book-b"], armed
    assert not [m for m in out if m.kind == "close"]
    assert seen.events("crypto_time_exit") == [] and seen.events("crypto_mae_exit") == []
    # ...and the gated reevaluator says it is gated, once, for this book
    off = seen.events("crypto_reeval_off")
    assert len(off) == 1 and off[0][2]["extra"]["user_id"] == "book-b", seen.said
    assert "TREZO_CRYPTO_REEVAL is off" in off[0][2]["reason"]


def test_rescore_collapse_closes_through_the_crypto_exit_path():
    row = _crypto_row("book-b", entry_at=_ago(days=1, hours=12))
    client = _Client({"paper_positions": [row]})
    seen = _Seen()

    async def _rv(r, price, side, at, strat, stop, target, emit=None,
                  agent_name=None):
        seen.reeval.append(dict(user_id=r["user_id"], price=price, side=side,
                                at=at, strat=strat, stop=stop, target=target,
                                bound=_bound_id()))
        return {"close": "reeval_tcs_collapse"}

    agent = pm.PositionMonitorAgent()
    with _registry(_two_books()), \
            _real_tick(client, 0.97, seen, reevaluate_position=_rv,
                       _crypto_reeval_enabled=lambda: True):
        out = _run(agent.tick())
    assert len(seen.reeval) == 1, seen.reeval
    call = seen.reeval[0]
    assert call["user_id"] == "book-b" and call["at"] == "crypto"
    assert call["bound"] == "acct2", "the reevaluator ran under another book"
    assert call["target"] is None, "lower_target must be unreachable for a coin"
    assert call["stop"] == 0.85 and call["strat"] == "crypto_swing"
    assert seen.liq == [("DOT", "crypto", "book-b", "acct2")], seen.liq
    assert seen.closes == [("book-b", "pos-book-b-DOT", "reeval")], seen.closes
    rr = seen.events("crypto_reeval")
    assert len(rr) == 1 and rr[0][1] == "DOT" and rr[0][2]["extra"]["user_id"] == "book-b"
    assert rr[0][2]["reason"].startswith("close reeval_tcs_collapse")
    ex = seen.events("crypto_reeval_exit")
    assert len(ex) == 1 and ex[0][2]["reason"] == "reeval_tcs_collapse"
    closes = [m for m in out if m.kind == "close"]
    assert closes and closes[0].payload["reason"] == "reeval"
    assert closes[0].payload["detail"] == "reeval_tcs_collapse"
    assert seen.events("crypto_reeval_off") == []


def test_reeval_is_not_reached_when_the_master_flag_is_off():
    """TREZO_CRYPTO_REEVAL=1 but TREZO_REEVAL_ENABLED off on the server:
    the coin is not re-scored and the row names the master flag."""
    row = _crypto_row("book-b", entry_at=_ago(days=1, hours=12))
    client = _Client({"paper_positions": [row]})
    seen = _Seen()
    agent = pm.PositionMonitorAgent()
    with _registry(_two_books()), \
            _real_tick(client, 0.97, seen, _crypto_reeval_enabled=lambda: True,
                       reeval_is_enabled=lambda: False):
        _run(agent.tick())
    assert seen.liq == [] and seen.closes == []
    off = seen.events("crypto_reeval_off")
    assert len(off) == 1 and "TREZO_REEVAL_ENABLED is off" in off[0][2]["reason"]


def test_mae_ceiling_catches_the_dot_geometry():
    """The 08-26 re-adoption geometry, but as a LANE-opened swing: entry
    0.925859, stop clamped to 0.799997 (-13.6%), price 0.8431 (-8.9%).
    The 8% ceiling closes it on the next tick instead of eight days later
    at -9%."""
    row = _crypto_row("book-b", entry_price=0.925859, stop_price=0.799997,
                      target_price=0.999928, entry_at=_ago(hours=6))
    client = _Client({"paper_positions": [row]})
    seen = _Seen()
    agent = pm.PositionMonitorAgent()
    with _registry(_two_books()), _real_tick(client, 0.8431, seen):
        out = _run(agent.tick())
    assert seen.liq == [("DOT", "crypto", "book-b", "acct2")], seen.liq
    assert seen.closes == [("book-b", "pos-book-b-DOT", "stop")], seen.closes
    rows = seen.events("crypto_mae_exit")
    assert len(rows) == 1 and rows[0][1] == "DOT", seen.said
    assert rows[0][2]["extra"]["user_id"] == "book-b"
    assert rows[0][2]["extra"]["exit_price"] == 0.8431
    assert "down 8.9% vs swing ceiling 8%" in rows[0][2]["reason"]
    closes = [m for m in out if m.kind == "close"]
    assert closes and closes[0].payload["reason"] == "stop"
    assert closes[0].payload["detail"].startswith("crypto_mae_exit")


def test_adopted_underwater_is_said_not_sold_without_the_yes():
    """The ACTUAL 08-26 DOT row: re-adopted, so its entry is the broker's
    inherited average. Default: one adopted_underwater row per hour per
    row, no order. With TREZO_CRYPTO_MAE_ADOPTED=1: sold, and the row
    says it was an adopted row."""
    row = _crypto_row("book-b", entry_price=0.925859, stop_price=0.799997,
                      target_price=0.999928, entry_at=_ago(hours=6),
                      source_payload={"adopted": True, "inherited": True,
                                      "geometry_clamped": True})
    client = _Client({"paper_positions": [row]})
    seen = _Seen()
    agent = pm.PositionMonitorAgent()
    with _registry(_two_books()), _real_tick(client, 0.8431, seen):
        _run(agent.tick())
        _run(agent.tick())        # second tick inside the hour: no repeat
    assert seen.liq == [] and seen.closes == [], (seen.liq, seen.closes)
    under = seen.events("adopted_underwater")
    assert len(under) == 1, [e for e, _, _ in seen.said]
    assert under[0][1] == "DOT" and under[0][2]["extra"]["user_id"] == "book-b"
    assert under[0][2]["extra"]["position_id"] == "pos-book-b-DOT"
    assert "TREZO_CRYPTO_MAE_ADOPTED=1" in under[0][2]["reason"]
    assert seen.events("crypto_mae_exit") == []
    # Mike's yes
    seen2 = _Seen()
    with _registry(_two_books()), \
            _real_tick(client, 0.8431, seen2, _crypto_mae_adopted_enabled=lambda: True):
        _run(agent.tick())
    assert seen2.liq == [("DOT", "crypto", "book-b", "acct2")], seen2.liq
    assert seen2.closes == [("book-b", "pos-book-b-DOT", "stop")]
    rows = seen2.events("crypto_mae_exit")
    assert len(rows) == 1 and "[adopted row" in rows[0][2]["reason"]


def test_fresh_or_winning_rows_are_left_alone():
    """(a) a fresh -3% loser, (b) a +2% winner ten days old, (c) a HODL
    -20% after a month, (d) a no_price_stop crypto row -5% at nine days:
    with the time rule ON and the MAE ceiling live, none of them is
    touched -- (b) proves winners never enter the rules, (c) that HODL
    rides, (d) that the NEQ-05 exemption holds."""
    rows = [
        _crypto_row("book-b", id="a-fresh", ticker="DOT",
                    entry_price=1.0, entry_at=_ago(hours=2)),
        _crypto_row("book-b", id="b-winner", ticker="DOT",
                    entry_price=0.95, entry_at=_ago(days=10)),
        _crypto_row("book-b", id="c-hodl", ticker="DOT", strategy="crypto_hodl",
                    entry_price=1.2125, stop_price=0.78, target_price=7.0,
                    entry_at=_ago(days=30)),
        _crypto_row("book-b", id="d-nps", ticker="DOT",
                    entry_price=1.0208, entry_at=_ago(days=9),
                    source_payload={"no_price_stop": True}),
    ]
    # one price for every row: 0.97 -> (a) -3%, (b) +2.1%, (c) -20%, (d) -5%
    client = _Client({"paper_positions": rows})
    seen = _Seen()
    agent = pm.PositionMonitorAgent()
    with _registry(_two_books()), \
            _real_tick(client, 0.97, seen, _crypto_time_exit_enabled=lambda: True):
        out = _run(agent.tick())
    assert seen.liq == [] and seen.closes == [], (seen.liq, seen.closes)
    assert not [m for m in out if m.kind == "close"]
    for ev, _t, _k in seen.said:
        assert not ev.endswith("_exit") and ev != "adopted_underwater", seen.said
    # the winner and the HODL never even reached the gated-reeval notice:
    # the only row that did is the fresh loser (a), once for the book
    off = seen.events("crypto_reeval_off")
    assert len(off) == 1 and off[0][2]["strategy"] == "crypto_swing", off


def test_per_book_keying():
    """Two DOT rows: book-a fresh (2h), book-b stale (5d). Exactly one
    liquidate, for book-b, executed while acct2 was bound; book-a's row
    is untouched; each row's entry_at judged on its own."""
    rows = [_crypto_row("book-a", entry_at=_ago(hours=2)),
            _crypto_row("book-b", entry_at=_ago(days=5))]
    client = _Client({"paper_positions": rows})
    seen = _Seen()
    agent = pm.PositionMonitorAgent()
    with _registry(_two_books()), \
            _real_tick(client, 0.94, seen, _crypto_time_exit_enabled=lambda: True):
        _run(agent.tick())
    assert seen.liq == [("DOT", "crypto", "book-b", "acct2")], seen.liq
    assert seen.closes == [("book-b", "pos-book-b-DOT", "time")], seen.closes
    rows_said = seen.events("crypto_time_exit")
    assert len(rows_said) == 1 and rows_said[0][2]["extra"]["user_id"] == "book-b"
    # the gated-reeval notice is per BOOK: both books said it, once each
    off = sorted(k["extra"]["user_id"] for _e, _t, k in seen.events("crypto_reeval_off"))
    assert off == ["book-a", "book-b"], off
    assert accounts.current_account() is None or _bound_id() is None


def test_reeval_stop_only_ratchets_up_and_target_reaches_tp_push():
    row = _crypto_row("book-b", entry_at=_ago(hours=5))
    client = _Client({"paper_positions": [row]})
    # (1) a LOWER stop from the reevaluator is ignored: 0.80 < row 0.85
    seen = _Seen()
    armed = []

    async def _rv_lower(r, price, side, at, strat, stop, target, emit=None,
                        agent_name=None):
        return {"stop": 0.80}

    async def _arm(r):
        armed.append(float(r.get("stop_price")))

    agent = pm.PositionMonitorAgent()
    with _registry(_two_books()), \
            _real_tick(client, 0.97, seen, reevaluate_position=_rv_lower,
                       _crypto_reeval_enabled=lambda: True, _arm_broker_stop=_arm):
        out = _run(agent.tick())
    assert seen.liq == [] and seen.closes == []
    assert armed == [0.85], armed              # the row's stop, not 0.80
    rr = seen.events("crypto_reeval")
    assert len(rr) == 1 and rr[0][2]["reason"].startswith("stop->0.85"), rr
    assert not [m for m in out if m.kind == "close"]
    # (2) a HIGHER stop is honoured for this tick's check (price 0.97 is
    # still above 0.90 -> hold); a returned target reaches _push_crypto_tp
    seen = _Seen()

    async def _rv_higher(r, price, side, at, strat, stop, target, emit=None,
                         agent_name=None):
        return {"stop": 0.90, "target": 1.05}

    with _registry(_two_books()), \
            _real_tick(client, 0.97, seen, reevaluate_position=_rv_higher,
                       _crypto_reeval_enabled=lambda: True):
        _run(agent.tick())
    assert seen.liq == [] and seen.closes == []
    assert seen.tp == [1.05], seen.tp
    rr = seen.events("crypto_reeval")
    assert len(rr) == 1 and rr[0][2]["reason"].startswith("stop->0.9"), rr


def test_a_row_that_is_already_closing_on_its_stop_is_not_rescored():
    """Skeptic (3): the reevaluator runs only when no ordinary exit fired
    this tick -- a row through its stop is liquidated as 'stop', never
    tightened, persisted and logged 'crypto_reeval' first."""
    row = _crypto_row("book-b", entry_at=_ago(days=2))
    client = _Client({"paper_positions": [row]})
    seen = _Seen()
    agent = pm.PositionMonitorAgent()
    with _registry(_two_books()), \
            _real_tick(client, 0.84, seen, _crypto_reeval_enabled=lambda: True,
                       _crypto_time_exit_enabled=lambda: True):
        _run(agent.tick())                # reevaluate_position stub RAISES if reached
    assert seen.liq == [("DOT", "crypto", "book-b", "acct2")]
    assert seen.closes == [("book-b", "pos-book-b-DOT", "stop")]
    assert seen.events("crypto_reeval") == [] and seen.events("crypto_mae_exit") == []


def test_a_broken_row_does_not_take_the_tick_down():
    """entry_price None on one crypto row: the row after it (another book)
    must still be managed on the same tick."""
    rows = [_crypto_row("book-a", entry_price=None, stop_price=None,
                        target_price=None, entry_at=_ago(days=9)),
            _crypto_row("book-b", entry_at=_ago(days=5))]
    client = _Client({"paper_positions": rows})
    seen = _Seen()
    agent = pm.PositionMonitorAgent()
    with _registry(_two_books()), \
            _real_tick(client, 0.94, seen, _crypto_time_exit_enabled=lambda: True):
        _run(agent.tick())
    assert seen.liq == [("DOT", "crypto", "book-b", "acct2")], seen.liq
    assert seen.closes == [("book-b", "pos-book-b-DOT", "time")]


# =======================================================================
# 5. the two latent crashes on the ratchet paths
# =======================================================================

def test_hodl_trail_ratchets_without_raising():
    """+50% HODL: the trail arms at +40% and locks 20% under price. Before
    2026-09-02 the persist path hit `if _breached:` -- a NameError."""
    row = {"id": "h1", "user_id": "book-b", "ticker": "SOL", "asset_type": "crypto",
           "side": "long", "quantity": 10.0, "entry_price": 1.0,
           "stop_price": 0.65, "strategy": "crypto_hodl", "broker": "alpaca"}
    client = _Client({"paper_positions": [row]})
    pushed = []

    async def _push(r, new_stop):
        pushed.append(new_stop)

    with _patched(pm, _supabase=lambda: client, _push_stop_to_broker=_push), \
            _patched(alog, record=lambda *a, **k: None):
        got = _run(pm._maybe_trail_hodl(row, 1.5))
    assert got is not None and abs(got - 1.2) < 1e-9, got
    assert client.updates == [("paper_positions", {"stop_price": got})]
    assert pushed == [got], pushed


def test_ladder_breached_rung_persists_and_is_said():
    """peak_price above a rung, price already back under the lock: the
    stop is persisted (the local stop-check sells this pass) and the
    ladder_lock_breached row is said -- through record()'s real
    signature, so it no longer raises. The broker push still happens
    (status quo: test_monitor_bookbound's extended KO/PG twin pins it;
    skipping it is a two-file change proposed in the track notes)."""
    row = {"id": "l1", "user_id": "book-b", "ticker": "DOT", "asset_type": "crypto",
           "side": "long", "quantity": 100.0, "entry_price": 1.0,
           "stop_price": 0.96, "peak_price": 1.02, "strategy": "crypto_swing",
           "broker": "alpaca"}
    client = _Client({"paper_positions": [row]})
    pushed, said = [], []

    async def _push(r, new_stop):
        pushed.append(new_stop)

    def _rec(event, ticker="", *_a, **kw):
        said.append((event, ticker, kw))

    from app.strategies.crypto import SWING_PROFIT_LADDER
    with _patched(pm, _supabase=lambda: client, _push_stop_to_broker=_push), \
            _patched(alog, record=_rec):
        got = _run(pm._maybe_ladder_stop(row, 1.005, SWING_PROFIT_LADDER))
    assert got is not None and abs(got - 1.011) < 1e-9, got   # +1.8% rung locks +1.1%
    assert client.updates == [("paper_positions", {"stop_price": got})]
    assert pushed == [got], pushed                       # status quo, see docstring
    assert [e for e, _, _ in said] == ["ladder_lock_breached"], said
    assert said[0][2]["extra"]["user_id"] == "book-b"
    assert said[0][2]["extra"]["peak"] == 1.02
    assert said[0][2]["extra"]["locked_stop"] == got
    # the un-breached case: pushed, and nothing said
    client2 = _Client({"paper_positions": [row]})
    row2 = {**row, "stop_price": 0.96, "peak_price": None}
    with _patched(pm, _supabase=lambda: client2, _push_stop_to_broker=_push), \
            _patched(alog, record=_rec):
        got2 = _run(pm._maybe_ladder_stop(row2, 1.02, SWING_PROFIT_LADDER))
    assert got2 is not None and pushed == [got, got2], (got2, pushed)
    assert len(said) == 1, said


if __name__ == "__main__":
    sys.exit(run_tests(dict(vars())))
