"""Book-keyed guards for RiskManagerAgent.on_message (audit 2026-09-01:
BI-04, KS-11, KS-12, TE-02, TE-07, TE-19, TE-24, EQ-5/BI-18).

This is the handler the four-day outage lived in (8/27 12:36 ET to
8/31 12:45 ET: every signal with a real direction raised inside
on_message and the bus router swallowed it). tests/test_risk_manager_
signal_path.py pins the ORDERING invariant by reading the source; this
suite EXECUTES the real on_message -- the unedited module, loaded via
_bootstrap.load_module -- with only the external seams stubbed at the
module attribute (Supabase, the broker, market data, Mem0, the activity
log). Every stub is put back when the test ends, because run_all
imports every suite into one process.

Rules pinned:
  - BI-04: a scanner crypto signal (no user_id) benches only the books
    whose per-coin halt is tripped, carries them as "benched_books" on
    the approval, and is vetoed only when EVERY book is benched. A
    user-scoped signal is judged for its own book alone.
  - KS-11: check_states() -> None is "could not evaluate": no veto, no
    exception, and the moment is logged (the fan-out fails closed).
  - KS-12: the user-set daily $ brake is judged per book via
    killswitch.daily_dollar_over; None (failed read) is not a veto.
  - TE-07: 'long' / 'short' are real directions at the market-bias gate.
  - TE-02: book_scoped passes through to the approval.
  - TE-24: approve_payload no longer carries the dead position_pct.
  - TE-19: the unbound primary-account margin read is gone; a stock
    signal never touches alpaca.get_account here.
  - EQ-5 / BI-18: the staleness bands are on the 0-100 TCS scale.
  - And the outage itself: a signal carrying a real direction reaches
    the gates BELOW the confidence bar without raising.

Deliberately dependency-free (no pytest, no .env, no network) so the
deploy gate (tests/run_all.py) can run them in a bare checkout.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _bootstrap import load_module, run_tests, stub_config  # noqa: E402

stub_config()
rm = load_module("app.agents.risk_manager")
ks = load_module("app.paper.killswitch")
persistence = load_module("app.runtime.persistence")
settings = load_module("app.runtime.settings")
overrides = load_module("app.runtime.overrides")
daily_goal = load_module("app.paper.daily_goal")
engine = load_module("app.paper.engine")
alp = load_module("app.brokers.alpaca")
market_filter = load_module("app.strategies.market_filter")
candles = load_module("app.data.candles")
activity_log = load_module("app.agents.activity_log")
library = load_module("app.knowledge.library")


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@contextlib.contextmanager
def _patched(mod, **attrs):
    """Swap module attributes and ALWAYS put the originals back --
    including ones whose original value is None (persistence._supabase)."""
    old = {k: getattr(mod, k) for k in attrs}
    try:
        for k, v in attrs.items():
            setattr(mod, k, v)
        yield
    finally:
        for k, v in old.items():
            setattr(mod, k, v)


# --- a recording stand-in for the supabase query-builder chain ----------

class _Query:
    def __init__(self, table: str, data: list):
        self.table_name = table
        self.calls: list[tuple] = []
        self._data = data

    def __getattr__(self, name):
        def _chain(*args, **kwargs):
            self.calls.append((name, args))
            return self
        return _chain

    def execute(self):
        return types.SimpleNamespace(data=self._data)


class _Client:
    def __init__(self, **tables):
        self._tables = tables
        self.queries: list[_Query] = []

    def table(self, name):
        q = _Query(name, list(self._tables.get(name, [])))
        self.queries.append(q)
        return q


# --- the desk: the real agent with every external seam stubbed ----------

def _open(uid="U"):
    return ks.KillSwitch(False, None, None)


def _halt(reason="Daily loss limit: down $400 (4.0%) today"):
    return ks.KillSwitch(True, "day", reason, mode="halt")


def _recovering():
    return ks.KillSwitch(False, "week", "Weekly loss limit", mode="recovery")


def _async(value):
    async def _f(*_a, **_k):
        return value
    return _f


def _raising(exc):
    async def _f(*_a, **_k):
        raise exc
    return _f


class _Calls:
    """Records what the seams were asked, so a test can prove which
    per-book function ran (and which did NOT)."""
    def __init__(self):
        self.coin_loss_halt: list = []
        self.by_book: list = []
        self.daily_dollar_over = 0
        self.alpaca_get_account = 0


@contextlib.contextmanager
def _desk(*, states, daily_over=frozenset(), verdicts=None,
          coin_veto=None, bias="unknown", rows=None):
    """Yield (agent, calls). `states` is what check_states returns (a
    dict of real KillSwitch objects, None, or an Exception instance to
    raise). `verdicts` is coin_loss_halt_by_book's answer; `coin_veto`
    is coin_loss_halt's (the user-scoped path)."""
    calls = _Calls()
    client = _Client(paper_positions=[], paper_accounts=[], profiles=[])

    if isinstance(states, BaseException):
        _check_states = _raising(states)
    else:
        _check_states = _async(states)

    async def _ddo(_client):
        calls.daily_dollar_over += 1
        return daily_over

    async def _clh(_client, sym, user_id=None):
        calls.coin_loss_halt.append((sym, user_id))
        return coin_veto

    async def _clhb(_client, sym):
        calls.by_book.append(sym)
        return dict(verdicts or {})

    async def _acct(*_a, **_k):
        calls.alpaca_get_account += 1
        raise AssertionError("TE-19: the risk gate must not read the "
                             "broker account unbound")

    _bias = market_filter.MarketBias(bias, None, None, f"test bias {bias}")

    # RV-RM-1 (review 2026-09-01): Mem0 is NOT reached through
    # app.config -- TrezoMemory.__init__ falls back to os.environ
    # MEM0_API_KEY when the stubbed settings lack the attribute, and
    # ops_relay runs this gate as a subprocess of the ENGINE with its
    # environment inherited. Unpatched, every approve below would fire a
    # real recall search plus a fire-and-forget log_decision ADD against
    # the 10k/month quota, from the deploy gate, on every deploy. Both
    # names are module globals of risk_manager, so patch them there.
    _no_mem = types.SimpleNamespace(available=False)

    with _patched(rm, _supabase=lambda: client,
                  get_memory=lambda: _no_mem,
                  recall_decision_context=lambda **_k: {"available": False}), \
         _patched(persistence, _supabase=client), \
         _patched(settings, get_bot_settings=lambda *_a, **_k: settings.BotSettings()), \
         _patched(overrides, get_disabled_reason=_async(None)), \
         _patched(daily_goal, goal_state=_async({"hit": False})), \
         _patched(engine, get_account=_async(
             {"current_cash_usd": 1_000.0, "vault_balance_usd": 0.0})), \
         _patched(alp, get_account=_acct), \
         _patched(market_filter, get_market_bias=_async(_bias)), \
         _patched(candles, fetch_candles_for=_async(list(rows or []))), \
         _patched(activity_log, record=lambda *_a, **_k: None), \
         _patched(library, search=lambda *_a, **_k: []), \
         _patched(ks, check_states=_check_states, daily_dollar_over=_ddo,
                  coin_loss_halt=_clh, coin_loss_halt_by_book=_clhb):
        yield rm.RiskManagerAgent(), calls


def _signal(**over):
    p = {"ticker": "XRP", "asset_type": "crypto", "direction": "bullish",
         "tcs": 90, "strategy": "crypto_swing", "stop_pct": 0.02,
         "target_pct": 0.05}
    p.update(over)
    return rm.AgentMessage(agent="crypto_scanner", kind="signal",
                           payload=p, confidence=0.9)


def _stock(**over):
    p = {"ticker": "KO", "asset_type": "stock", "direction": "bullish",
         "tcs": 90, "strategy": "swing"}
    p.update(over)
    return rm.AgentMessage(agent="pattern_detection", kind="signal",
                           payload=p, confidence=0.9)


def _verdict(out):
    """The one approve/veto in a handler result (info notes are advisory)."""
    ms = [m for m in out if m.kind in ("approve", "veto")]
    assert len(ms) == 1, [(m.kind, m.payload) for m in out]
    return ms[0]


THREE_OPEN = {"A": _open(), "B": _open(), "C": _open()}


# --- BI-04: the per-coin bench is per book --------------------------------

def test_scanner_crypto_signal_two_benched_one_open_is_approved_with_benched_books():
    """THE case: the primary and acct2 have lost their XRP slice today,
    acct3 has not. The old code vetoed XRP for everyone."""
    verdicts = {"A": (True, "XRP per-coin daily loss limit: down $40 today (limit $30)"),
                "B": (True, "XRP per-coin daily loss limit: down $35 today (limit $30)"),
                "C": (False, "")}
    with _desk(states=THREE_OPEN, verdicts=verdicts) as (agent, calls):
        v = _verdict(_run(agent.on_message(_signal())))
    assert v.kind == "approve", v.payload
    assert v.payload.get("benched_books") == ["A", "B"], v.payload
    assert calls.by_book == ["XRP"], "the by-book evaluator must run for a scanner signal"
    assert calls.coin_loss_halt == [], "the single-book verdict must NOT run without a user_id"


def test_scanner_crypto_signal_with_every_book_benched_is_vetoed():
    verdicts = {"A": (True, "XRP per-coin daily loss limit: down $40 today (limit $30)"),
                "B": (True, "XRP per-coin daily loss limit: down $35 today (limit $30)"),
                "C": (True, "XRP per-coin daily loss limit: down $31 today (limit $30)")}
    with _desk(states=THREE_OPEN, verdicts=verdicts) as (agent, _):
        v = _verdict(_run(agent.on_message(_signal())))
    assert v.kind == "veto", v.payload
    assert "per-coin" in v.payload["reason"] and "all 3 books benched" in v.payload["reason"], v.payload


def test_scanner_crypto_signal_with_no_book_benched_carries_no_bench_list():
    verdicts = {"A": (False, ""), "B": (False, ""), "C": (False, "")}
    with _desk(states=THREE_OPEN, verdicts=verdicts) as (agent, _):
        v = _verdict(_run(agent.on_message(_signal())))
    assert v.kind == "approve"
    assert "benched_books" not in v.payload, v.payload


def test_a_failed_by_book_read_benches_nobody_here():
    """coin_loss_halt_by_book returns {} on a failed ledger read (and
    logs it). That is not 'every book is benched' -- it is 'could not
    look' -- so the signal continues to the fan-out with no bench."""
    with _desk(states=THREE_OPEN, verdicts={}) as (agent, _):
        v = _verdict(_run(agent.on_message(_signal())))
    assert v.kind == "approve"
    assert "benched_books" not in v.payload


def test_user_scoped_crypto_signal_is_judged_for_its_own_book_only():
    with _desk(states=THREE_OPEN, coin_veto=None) as (agent, calls):
        v = _verdict(_run(agent.on_message(_signal(user_id="B"))))
    assert v.kind == "approve" and v.payload["user_id"] == "B"
    assert calls.coin_loss_halt == [("XRP", "B")], calls.coin_loss_halt
    assert calls.by_book == [], "a pinned signal never walks the other books"


def test_user_scoped_crypto_signal_over_its_own_limit_is_vetoed_for_that_book():
    why = "XRP per-coin daily loss limit: down $40 today (limit $30)"
    with _desk(states=THREE_OPEN, coin_veto=why) as (agent, _):
        v = _verdict(_run(agent.on_message(_signal(user_id="B"))))
    assert v.kind == "veto" and v.payload["reason"] == why
    assert v.payload["user_id"] == "B", "the veto must be attributed to the book it judged"


# --- KS-11: None from check_states is 'cannot evaluate' -------------------

def test_check_states_none_does_not_veto_and_does_not_raise():
    """A dead paper_accounts read must not read as 'no halts' (the old
    {} fallback) AND must not become a platform-wide veto: the fan-out
    fails closed per book. It must be SAID, though."""
    saved = rm._LAST_KS_UNKNOWN_LOG
    try:
        rm._LAST_KS_UNKNOWN_LOG = 0.0
        with _desk(states=None, verdicts={"A": (False, "")}) as (agent, calls):
            out = _run(agent.on_message(_signal()))
        v = _verdict(out)
        assert v.kind == "approve", v.payload
        assert calls.daily_dollar_over == 0, "no books to judge -> no $ brake read"
        assert rm._LAST_KS_UNKNOWN_LOG > 0.0, "the 'could not evaluate' moment was not logged"
    finally:
        rm._LAST_KS_UNKNOWN_LOG = saved


def test_check_states_raising_is_also_cannot_evaluate():
    saved = rm._LAST_KS_UNKNOWN_LOG
    try:
        rm._LAST_KS_UNKNOWN_LOG = 0.0
        with _desk(states=RuntimeError("supabase down"),
                   verdicts={"A": (False, "")}) as (agent, _):
            v = _verdict(_run(agent.on_message(_signal())))
        assert v.kind == "approve", v.payload
        assert rm._LAST_KS_UNKNOWN_LOG > 0.0
    finally:
        rm._LAST_KS_UNKNOWN_LOG = saved


def test_the_unknown_log_is_throttled_not_spammed():
    saved = rm._LAST_KS_UNKNOWN_LOG
    try:
        rm._LAST_KS_UNKNOWN_LOG = 0.0
        rm._note_kill_switch_unknown("XRP")
        first = rm._LAST_KS_UNKNOWN_LOG
        rm._note_kill_switch_unknown("XRP")
        assert rm._LAST_KS_UNKNOWN_LOG == first, "a veto storm must not become a log storm"
    finally:
        rm._LAST_KS_UNKNOWN_LOG = saved


def test_every_book_hard_halted_is_still_a_veto():
    """None is not a veto; a real answer of 'all halted' still is."""
    states = {"A": _halt(), "B": _halt(), "C": _halt()}
    with _desk(states=states, verdicts={}) as (agent, _):
        v = _verdict(_run(agent.on_message(_signal())))
    assert v.kind == "veto"
    assert v.payload["reason"].startswith("Kill-switch [all books]"), v.payload


def test_one_halted_book_does_not_veto_the_others():
    states = {"A": _halt(), "B": _open(), "C": _open()}
    with _desk(states=states, verdicts={}) as (agent, _):
        v = _verdict(_run(agent.on_message(_signal())))
    assert v.kind == "approve", v.payload


# --- KS-12: the daily $ brake, per book, None on failure ------------------

def test_daily_dollar_over_is_read_from_killswitch_per_book():
    with _desk(states=THREE_OPEN, daily_over={"A"}, verdicts={}) as (agent, calls):
        v = _verdict(_run(agent.on_message(_signal())))
    assert calls.daily_dollar_over == 1, "the $ brake must come from killswitch.daily_dollar_over"
    assert v.kind == "approve", "one book over its $ limit must not veto the other two"


def test_every_book_over_its_dollar_limit_is_a_veto():
    with _desk(states=THREE_OPEN, daily_over={"A", "B", "C"}, verdicts={}) as (agent, _):
        v = _verdict(_run(agent.on_message(_signal())))
    assert v.kind == "veto"
    assert "daily $ loss limit" in v.payload["reason"], v.payload


def test_daily_dollar_over_none_is_unknown_not_a_veto():
    with _desk(states=THREE_OPEN, daily_over=None, verdicts={}) as (agent, _):
        v = _verdict(_run(agent.on_message(_signal())))
    assert v.kind == "approve", v.payload


def test_the_old_in_module_drawdown_helper_is_gone():
    assert not hasattr(rm, "_users_in_daily_drawdown"), (
        "KS-12: the $ brake lives in killswitch.daily_dollar_over now; a "
        "second copy here would drift")


# --- the outage: a real direction must reach the gates below the bar -----

def test_a_signal_with_a_real_direction_never_raises_unbound_local():
    """8/27-8/31: recovery_bump was read before it was assigned and every
    bullish signal died inside on_message. Drive a stock signal through
    the whole bar; the liquidity gate BELOW it must be the one that
    speaks (no candles -> 'No price data')."""
    for direction in ("bullish", "bearish", "long", "short"):
        with _desk(states=THREE_OPEN, bias="unknown", rows=[]) as (agent, calls):
            try:
                out = _run(agent.on_message(_stock(direction=direction)))
            except UnboundLocalError as e:  # pragma: no cover - the outage
                raise AssertionError(f"THE OUTAGE IS BACK for {direction!r}: {e}")
        v = _verdict(out)
        assert v.kind == "veto" and "No price data" in v.payload["reason"], (
            direction, v.payload)
        assert calls.alpaca_get_account == 0, (
            "TE-19: the risk gate read the broker account unbound")


# --- TE-07: 'long' / 'short' at the market-bias gate ----------------------

def test_long_direction_is_treated_as_long_by_the_market_bias_gate():
    """Bearish tape, 'long' signal: blocked as a LONG. Before TE-07 it
    was mapped to short and sailed through an opposing tape."""
    with _desk(states=THREE_OPEN, bias="bearish", rows=[]) as (agent, _):
        v = _verdict(_run(agent.on_message(_stock(direction="long"))))
    assert v.kind == "veto" and "long trades blocked" in v.payload["reason"], v.payload


def test_bullish_still_maps_to_long():
    with _desk(states=THREE_OPEN, bias="bearish", rows=[]) as (agent, _):
        v = _verdict(_run(agent.on_message(_stock(direction="bullish"))))
    assert "long trades blocked" in v.payload["reason"], v.payload


def test_short_direction_is_treated_as_short_by_the_market_bias_gate():
    with _desk(states=THREE_OPEN, bias="bullish", rows=[]) as (agent, _):
        v = _verdict(_run(agent.on_message(_stock(direction="short"))))
    assert v.kind == "veto" and "short trades blocked" in v.payload["reason"], v.payload


def test_a_short_in_a_bearish_tape_passes_the_bias_gate():
    """Control: the gate only opposes; a short in a down tape gets
    through to the next gate (liquidity, which has no candles here)."""
    with _desk(states=THREE_OPEN, bias="bearish", rows=[]) as (agent, _):
        v = _verdict(_run(agent.on_message(_stock(direction="short"))))
    assert "No price data" in v.payload["reason"], v.payload


# --- TE-02 / TE-24: the approve payload -----------------------------------

def test_book_scoped_passes_through_to_the_approval():
    with _desk(states=THREE_OPEN, coin_veto=None) as (agent, _):
        v = _verdict(_run(agent.on_message(_signal(user_id="B", book_scoped=True))))
    assert v.kind == "approve" and v.payload.get("book_scoped") is True, v.payload


def test_book_scoped_absent_stays_absent():
    with _desk(states=THREE_OPEN, verdicts={}) as (agent, _):
        v = _verdict(_run(agent.on_message(_signal())))
    assert v.kind == "approve" and "book_scoped" not in v.payload, v.payload


def test_position_pct_is_gone_from_the_approval():
    with _desk(states=THREE_OPEN, verdicts={}) as (agent, _):
        v = _verdict(_run(agent.on_message(_signal())))
    assert v.kind == "approve"
    assert "position_pct" not in v.payload, "TE-24: dead field, no reader"
    assert not hasattr(rm.RiskManagerAgent, "DEFAULT_PCT_OF_ACCOUNT")


def test_the_unbound_margin_cache_is_gone():
    assert not hasattr(rm.RiskManagerAgent, "_margin_snap"), (
        "TE-19: one class-level broker snapshot for three books")


# --- EQ-5 / BI-18: staleness bands on the 0-100 scale ---------------------

def test_stale_bands_are_on_the_0_100_scale():
    f = rm.RiskManagerAgent._stale_deadline_for
    assert f(90) == 60, "a 90 is urgent"
    assert f(70) == 60
    assert f(69) == 180
    assert f(50) == 180
    assert f(49) == 300
    assert f(10) == 300


def test_an_agent_urgency_tag_still_wins_over_the_band():
    f = rm.RiskManagerAgent._stale_deadline_for
    assert f(10, "urgent") == 60
    assert f(95, "low") == 300


if __name__ == "__main__":
    sys.exit(run_tests(dict(globals())))
