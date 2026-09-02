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
    PINNED signal (user_id + book_scoped) is judged for its own book
    alone; a bare user_id (pattern_detection's provenance stamp on a
    COIN_MAP symbol) walks every book like a scanner signal
    (vf:single-book-gates).
  - KS-11: check_states() -> None is "could not evaluate": no veto, no
    exception, and the moment is logged (the fan-out fails closed).
  - KS-12: the user-set daily $ brake is judged per book via
    killswitch.daily_dollar_over; None (failed read) is not a veto.
  - TE-07: 'long' / 'short' are real directions at the market-bias gate.
  - TE-02: book_scoped passes through to the approval.
  - TE-24: approve_payload no longer carries the dead position_pct.
  - TE-19: the unbound primary-account margin read is gone; a stock
    signal never touches alpaca.get_account here.
  - EQ-5 / BI-18: the staleness bands are on the 0-100 TCS scale (and,
    review 2026-09-01, the reattribution / rotation gates too).
  - And the outage itself: a signal carrying a real direction reaches
    the gates BELOW the confidence bar without raising.
  - BI-03 (review 2026-09-01): a scanner signal (no user_id) is judged
    at the LOWEST enabled book's floor via the REAL
    settings.min_tcs_floor_across_books; a user-scoped signal keeps its
    own book's floor; a failed enumeration falls open to the bare read.
  - Pinned kill-switch (review 2026-09-01; vf:single-book-gates): a
    signal with user_id AND book_scoped=True is judged for THAT book
    alone -- halted -> veto naming the book, its daily $ limit -> veto,
    recovery -> its lane policy and the RECOVERY_TCS_BUMP on its bar; a
    halted neighbour changes nothing. A BARE user_id is provenance (the
    pattern_detection stamp): trade_execution fans that approval out to
    every book, so the risk gate judges it by the all-books rule -- a
    halted / $-limited / recovering origin book must NOT veto or bump
    the sibling books' copies (the 2026-08-27 failure class). The same
    contract binds the per-coin bench (BI-04 above).
  - NEQ-05 / G3: no_price_stop=True gets NO stop geometry (no default
    fill, no harmonizer, nothing forwarded) and the flag rides the
    approval with the lane's max_notional.

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
cap_tiers = load_module("app.strategies.cap_tiers")


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
          coin_veto=None, bias="unknown", rows=None, books=None,
          pass_market=False):
    """Yield (agent, calls). `states` is what check_states returns (a
    dict of real KillSwitch objects, None, or an Exception instance to
    raise). `verdicts` is coin_loss_halt_by_book's answer; `coin_veto`
    is coin_loss_halt's (the user-scoped path).

    `books` (BI-03): {user_id: BotSettings} -- the per-book rows
    get_bot_settings(uid) answers with, AND the enabled-book list the
    REAL settings.min_tcs_floor_across_books enumerates (its
    _enabled_book_ids seam). A bare get_bot_settings() -- the PRIMARY
    row -- stays the default BotSettings() (floor 70) so the test can
    tell "judged at the primary's floor" from "judged at the lowest".

    `pass_market`: the stock market-quality gates (liquidity,
    overextension, spread) answer None and one candle is on the tape,
    so a STOCK signal reaches the approval instead of dying at 'No
    price data'; the cap tier reads 'unknown' (no fundamentals fetch)."""
    calls = _Calls()
    client = _Client(paper_positions=[], paper_accounts=[], profiles=[])
    _books = dict(books or {})

    def _gbs(user_id=None, *_a, **_k):
        if user_id and str(user_id) in _books:
            return _books[str(user_id)]
        return settings.BotSettings()

    if pass_market and rows is None:
        rows = [types.SimpleNamespace(close=100.0)]
    _mkt = ({"liquidity_check": lambda *_a, **_k: None,
             "overextension_check": lambda *_a, **_k: None,
             "spread_quality_check": _async(None)}
            if pass_market else {})

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
         _patched(settings, get_bot_settings=_gbs,
                  _enabled_book_ids=lambda: list(_books)), \
         _patched(overrides, get_disabled_reason=_async(None)), \
         _patched(daily_goal, goal_state=_async({"hit": False})), \
         _patched(engine, get_account=_async(
             {"current_cash_usd": 1_000.0, "vault_balance_usd": 0.0})), \
         _patched(alp, get_account=_acct), \
         _patched(market_filter, get_market_bias=_async(_bias), **_mkt), \
         _patched(candles, fetch_candles_for=_async(list(rows or []))), \
         _patched(cap_tiers, tier_for=_async("unknown")), \
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
    """Pinned (user_id + book_scoped): the own-book read runs, the
    by-book walk does not."""
    with _desk(states=THREE_OPEN, coin_veto=None) as (agent, calls):
        v = _verdict(_run(agent.on_message(_signal(user_id="B", book_scoped=True))))
    assert v.kind == "approve" and v.payload["user_id"] == "B"
    assert calls.coin_loss_halt == [("XRP", "B")], calls.coin_loss_halt
    assert calls.by_book == [], "a pinned signal never walks the other books"


def test_user_scoped_crypto_signal_over_its_own_limit_is_vetoed_for_that_book():
    why = "XRP per-coin daily loss limit: down $40 today (limit $30)"
    with _desk(states=THREE_OPEN, coin_veto=why) as (agent, _):
        v = _verdict(_run(agent.on_message(_signal(user_id="B", book_scoped=True))))
    assert v.kind == "veto" and v.payload["reason"] == why
    assert v.payload["user_id"] == "B", "the veto must be attributed to the book it judged"


def test_provenance_crypto_signal_walks_every_books_bench_not_just_the_origin():
    """vf:single-book-gates: pattern_detection stamps a bare origin-book
    user_id on a COIN_MAP watchlist signal and the fan-out sends it to
    every book. Origin A benched, B and C open -> approve carrying
    benched_books == ["A"] from the by-book walk; the own-book read
    (which would have vetoed everyone) never runs."""
    verdicts = {"A": (True, "XRP per-coin daily loss limit: down $40 today (limit $30)"),
                "B": (False, ""), "C": (False, "")}
    with _desk(states=THREE_OPEN, verdicts=verdicts) as (agent, calls):
        v = _verdict(_run(agent.on_message(_signal(user_id="A"))))
    assert v.kind == "approve", v.payload
    assert v.payload.get("benched_books") == ["A"], v.payload
    assert calls.by_book == ["XRP"], "a provenance stamp must walk every book"
    assert calls.coin_loss_halt == [], "the own-book read is for pinned signals only"


def test_provenance_crypto_signal_with_a_benched_sibling_carries_that_book():
    """The other half of the same defect: origin A open, sibling B
    benched. The own-book read would have carried NO benched_books and
    the fan-out (which trusts that list) would have let B trade."""
    verdicts = {"A": (False, ""),
                "B": (True, "XRP per-coin daily loss limit: down $35 today (limit $30)"),
                "C": (False, "")}
    with _desk(states=THREE_OPEN, verdicts=verdicts) as (agent, _):
        v = _verdict(_run(agent.on_message(_signal(user_id="A"))))
    assert v.kind == "approve", v.payload
    assert v.payload.get("benched_books") == ["B"], v.payload


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
    # Review 2026-09-01 (rv:test-contract :320): these two calls ran
    # OUTSIDE _desk, so the real activity_log.record appended a
    # kill_switch_unknown row to logs/activity-<today>.jsonl on every
    # gate run -- the live feed ops_relay mirrors. record is imported
    # late inside the function, so the module-attribute patch binds.
    saved = rm._LAST_KS_UNKNOWN_LOG
    try:
        rm._LAST_KS_UNKNOWN_LOG = 0.0
        with _patched(activity_log, record=lambda *_a, **_k: None):
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


# --- BI-03: an unscoped signal is judged at the LOWEST enabled floor -------
# (review 2026-09-01, rv:scanners-scale :462). Two books, floors 40 and
# 70. The scanners emit at 40 now; the risk gate used to judge at the
# PRIMARY's 70 and veto before the fan-out's per-book gate ever ran, so
# the 40 book was starved between 40 and 70. tests/test_fanout_bookkeyed
# proves the other half: the same approval executes on the 40 book only.

TWO_OPEN = {"A": _open(), "B": _open()}


def _two_floors():
    return {"A": settings.BotSettings(tcs_threshold=40),
            "B": settings.BotSettings(tcs_threshold=70)}


def test_unscoped_signal_is_judged_at_the_lowest_book_floor():
    with _desk(states=TWO_OPEN, books=_two_floors(), pass_market=True) as (agent, _):
        v = _verdict(_run(agent.on_message(_stock(tcs=55))))
    assert v.kind == "approve", v.payload
    assert v.payload.get("user_id") is None, "a scanner signal stays unscoped"


def test_unscoped_signal_under_every_floor_is_still_vetoed():
    with _desk(states=TWO_OPEN, books=_two_floors(), pass_market=True) as (agent, _):
        v = _verdict(_run(agent.on_message(_stock(tcs=35))))
    assert v.kind == "veto" and "below threshold 40" in v.payload["reason"], v.payload


def test_user_scoped_signal_keeps_its_own_books_floor():
    """The 70 book's own signal at 55 is judged at 70 -- not at the
    platform minimum, which would let one book's slider loosen another's."""
    with _desk(states=TWO_OPEN, books=_two_floors(), pass_market=True) as (agent, _):
        v = _verdict(_run(agent.on_message(_stock(tcs=55, user_id="B"))))
    assert v.kind == "veto" and "below threshold 70" in v.payload["reason"], v.payload


def test_a_failed_book_enumeration_falls_open_to_the_bare_read():
    """min_tcs_floor_across_books cannot enumerate books -> the old
    single-row read (the primary's 70) decides, as it always did."""

    def _boom():
        raise RuntimeError("accounts.json unreadable")

    with _desk(states=TWO_OPEN, books=_two_floors(), pass_market=True) as (agent, _), \
         _patched(settings, _enabled_book_ids=_boom):
        v = _verdict(_run(agent.on_message(_stock(tcs=55))))
    assert v.kind == "veto" and "below threshold 70" in v.payload["reason"], v.payload


# --- PINNED signals: the kill-switch judges THAT book alone ----------------
# (review 2026-09-01, rv:killswitch-contracts). The all-books rule asks
# "can ANY book act?" -- right for a signal every book will see, wrong
# for a signal raised FOR one book: B's own signal while B is halted and
# A is open used to be approved. "Pinned" means user_id AND book_scoped
# =True, exactly what trade_execution.on_message pins to one book
# (vf:single-book-gates) -- these six say so explicitly.

def test_user_scoped_signal_on_a_halted_book_is_vetoed_naming_that_book():
    with _desk(states={"A": _open(), "B": _halt()}, coin_veto=None) as (agent, _):
        v = _verdict(_run(agent.on_message(_signal(user_id="B", book_scoped=True))))
    assert v.kind == "veto", v.payload
    assert v.payload["reason"].startswith("Kill-switch [book B]"), v.payload["reason"]
    assert "Daily loss limit" in v.payload["reason"]
    assert v.payload["user_id"] == "B", "the veto is attributed to the book it judged"


def test_user_scoped_signal_on_an_open_book_ignores_a_halted_neighbour():
    with _desk(states={"A": _halt(), "B": _open()}, coin_veto=None) as (agent, _):
        v = _verdict(_run(agent.on_message(_signal(user_id="B", book_scoped=True))))
    assert v.kind == "approve" and v.payload["user_id"] == "B", v.payload


def test_user_scoped_signal_at_its_own_daily_dollar_limit_is_vetoed():
    with _desk(states=TWO_OPEN, daily_over={"B"}, coin_veto=None) as (agent, calls):
        v = _verdict(_run(agent.on_message(_signal(user_id="B", book_scoped=True))))
    assert v.kind == "veto" and "daily $ loss limit" in v.payload["reason"], v.payload
    assert v.payload["reason"].startswith("Kill-switch [book B]")
    assert calls.daily_dollar_over == 1


def test_user_scoped_signal_is_not_braked_by_a_neighbours_dollar_limit():
    with _desk(states=TWO_OPEN, daily_over={"A"}, coin_veto=None) as (agent, _):
        v = _verdict(_run(agent.on_message(_signal(user_id="B", book_scoped=True))))
    assert v.kind == "approve", v.payload


def test_user_scoped_signal_on_a_recovering_book_faces_the_recovery_bump():
    """crypto_swing runs at the 35 crypto floor; B in weekly recovery
    raises ITS bar to 45 (RECOVERY_TCS_BUMP) even though A is open --
    the all-books rule only bumped when EVERY book was recovering."""
    states = {"A": _open(), "B": _recovering()}
    with _desk(states=states, coin_veto=None) as (agent, _):
        v = _verdict(_run(agent.on_message(_signal(user_id="B", book_scoped=True, tcs=40))))
    assert v.kind == "veto", v.payload
    assert f"below threshold {35 + ks.RECOVERY_TCS_BUMP}" in v.payload["reason"], v.payload
    assert "weekly recovery" in v.payload["reason"] and "book B" in v.payload["reason"]
    with _desk(states=states, coin_veto=None) as (agent, _):
        v = _verdict(_run(agent.on_message(_signal(user_id="B", book_scoped=True, tcs=50))))
    assert v.kind == "approve", v.payload


def test_user_scoped_signal_on_a_recovering_book_suspends_speculative_lanes():
    with _desk(states={"A": _open(), "B": _recovering()}, coin_veto=None) as (agent, _):
        v = _verdict(_run(agent.on_message(
            _signal(user_id="B", book_scoped=True, strategy="crypto_scalp", tcs=90))))
    assert v.kind == "veto" and "recovery suspends crypto_scalp" in v.payload["reason"], v.payload


def test_a_scanner_signal_still_uses_the_all_books_rule():
    """Control: unscoped, one halted + one open -> approve, unchanged."""
    with _desk(states={"A": _halt(), "B": _open()}, verdicts={}) as (agent, _):
        v = _verdict(_run(agent.on_message(_signal())))
    assert v.kind == "approve", v.payload


# --- vf:single-book-gates: a BARE user_id is provenance, not a pin ---------
# pattern_detection stamps payload["user_id"] = <origin book> on every
# watchlist signal and never sets book_scoped; trade_execution.on_message
# treats exactly that shape as PROVENANCE (origin_book, fan out to every
# book) and pins only user_id AND book_scoped. Between 2026-09-01's
# rv:killswitch-contracts change and this fix the risk gate read the bare
# user_id as a pin, so the primary hard-halted / over its $ limit vetoed
# the 25k/75k copies too -- the 2026-08-27 failure class, back for the
# stock pattern lane. These controls drive the REAL on_message with the
# producer's exact payload shape.

def test_provenance_user_id_on_a_halted_origin_book_is_not_a_veto():
    """A: halted origin book, B: open. Bare user_id="A" -> the all-books
    rule -> approve; the fan-out skips A itself. The provenance stamp
    still rides the approval so execution can record origin_book."""
    with _desk(states={"A": _halt(), "B": _open()}, verdicts={}) as (agent, _):
        v = _verdict(_run(agent.on_message(_signal(user_id="A"))))
    assert v.kind == "approve", v.payload
    assert v.payload.get("user_id") == "A" and "book_scoped" not in v.payload, v.payload


def test_provenance_user_id_on_an_origin_book_over_its_dollar_limit_is_not_a_veto():
    with _desk(states=TWO_OPEN, daily_over={"A"}, verdicts={}) as (agent, _):
        v = _verdict(_run(agent.on_message(_signal(user_id="A"))))
    assert v.kind == "approve", v.payload


def test_provenance_user_id_on_a_recovering_origin_book_does_not_bump_the_bar():
    """The pinned rule adds RECOVERY_TCS_BUMP for a recovering book; a
    provenance-only origin book in recovery must not raise the bar for
    the copies the open books will take (crypto floor 35, tcs 40), nor
    suspend a speculative lane for them."""
    with _desk(states={"A": _recovering(), "B": _open()}, verdicts={}) as (agent, _):
        v = _verdict(_run(agent.on_message(_signal(user_id="A", tcs=40))))
    assert v.kind == "approve", v.payload
    with _desk(states={"A": _recovering(), "B": _open()}, verdicts={}) as (agent, _):
        v = _verdict(_run(agent.on_message(
            _signal(user_id="A", strategy="crypto_scalp", tcs=90))))
    assert v.kind == "approve", v.payload


def test_provenance_stock_signal_from_a_halted_primary_still_reaches_the_siblings():
    """The exact 2026-08-27 shape on the stock pattern lane: a
    pattern_detection signal stamped with the primary's id while the
    primary is hard-halted and a sibling is open -> approve."""
    with _desk(states={"A": _halt(), "B": _open()}, pass_market=True) as (agent, _):
        v = _verdict(_run(agent.on_message(_stock(user_id="A"))))
    assert v.kind == "approve", v.payload
    assert v.payload.get("user_id") == "A", v.payload


def test_provenance_user_id_is_no_free_pass_when_every_book_is_halted():
    """Provenance falls through to the all-books rule, not past it."""
    with _desk(states={"A": _halt(), "B": _halt()}, verdicts={}) as (agent, _):
        v = _verdict(_run(agent.on_message(_signal(user_id="A"))))
    assert v.kind == "veto", v.payload
    assert v.payload["reason"].startswith("Kill-switch [all books]"), v.payload["reason"]


def test_pinned_signal_on_a_halted_book_a_is_vetoed_naming_a():
    """The pin still binds: user_id="A" WITH book_scoped while A is
    halted and B is open -> veto naming A, attributed to A."""
    with _desk(states={"A": _halt(), "B": _open()}, coin_veto=None) as (agent, _):
        v = _verdict(_run(agent.on_message(_signal(user_id="A", book_scoped=True))))
    assert v.kind == "veto", v.payload
    assert v.payload["reason"].startswith("Kill-switch [book A]"), v.payload["reason"]
    assert v.payload["user_id"] == "A", v.payload


# --- NEQ-05 / G3: no_price_stop gets NO stop geometry -----------------------
# The dividend ladder holds through drawdowns by design; its producer says
# no_price_stop=True. The cap-tier block used to fill the DEFAULT 5% stop
# on exactly that signal.

def _ladder(**over):
    p = {"ticker": "PG", "asset_type": "stock", "direction": "bullish",
         "tcs": 75, "strategy": "dividend_lt", "user_id": "B",
         "no_price_stop": True, "max_notional": 420.0}
    p.update(over)
    return rm.AgentMessage(agent="dividend_lt", kind="signal",
                           payload=p, confidence=0.6)


def test_no_price_stop_signal_gets_no_stop_geometry_and_carries_the_flag():
    with _desk(states=TWO_OPEN, pass_market=True) as (agent, _):
        v = _verdict(_run(agent.on_message(_ladder())))
    assert v.kind == "approve", v.payload
    assert v.payload.get("no_price_stop") is True
    assert "stop_pct" not in v.payload and "target_pct" not in v.payload, v.payload
    assert v.payload.get("max_notional") == 420.0, "the lane cap must ride the approval"
    assert v.payload["user_id"] == "B"
    assert "no price stop" in v.payload["thesis"]["exit_watch"]


def test_the_same_signal_without_the_flag_still_gets_the_default_stop():
    """Control: proves the block the flag skips is live -- without the
    flag the default stop IS filled in (that default is the NEQ-05 hole)."""
    m = _ladder()
    m.payload.pop("no_price_stop")
    with _desk(states=TWO_OPEN, pass_market=True) as (agent, _):
        v = _verdict(_run(agent.on_message(m)))
    assert v.kind == "approve", v.payload
    assert "no_price_stop" not in v.payload
    assert v.payload.get("stop_pct") == 0.05, v.payload


def test_no_price_stop_wins_over_a_stop_the_producer_also_sent():
    """Contradictory input: the flag is the contract; no stop is forwarded."""
    with _desk(states=TWO_OPEN, pass_market=True) as (agent, _):
        v = _verdict(_run(agent.on_message(_ladder(stop_pct=0.03, target_pct=0.09))))
    assert v.kind == "approve" and v.payload.get("no_price_stop") is True
    assert "stop_pct" not in v.payload and "target_pct" not in v.payload, v.payload


# --- EQ-5 leftovers on the 0-1000 scale (review 2026-09-01) ----------------

def test_the_reattribution_and_rotation_gates_are_on_the_0_100_scale():
    import inspect
    src = inspect.getsource(rm)
    assert "if fits and tcs >= 600" not in src,         "the Mem0 reattribution hook can never fire at >= 600"
    assert "weakest_score < 75" not in src,         "no 0-100 signal clears a 75-point rotation gap"
    assert "if fits and tcs >= 60:" in src
    assert "incoming_tcs - weakest_score < 8" in src


if __name__ == "__main__":
    sys.exit(run_tests(dict(globals())))
