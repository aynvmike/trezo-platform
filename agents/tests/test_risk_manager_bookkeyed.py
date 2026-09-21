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
  - Each unpinned observation produces one independently judged, pinned
    verdict per registered book. A bare user_id is origin provenance;
    it cannot impose that account's settings or losses on sibling books.
  - A pinned signal is evaluated only for its named, registered book.
    Missing/unknown books and an unavailable registry never fall back to
    the primary account.
  - Kill-switches, daily dollar limits, per-coin loss limits, recovery
    and confidence floors are enforced separately for each book.
  - Unknown kill-switch reads are logged; execution remains responsible
    for its fail-closed checks before an order is submitted.
  - Real directions reach the gates below the confidence bar without an
    UnboundLocalError; long/short market bias remains direction aware.
  - Approvals preserve the book pin and origin provenance, contain no
    dead position_pct, and respect the no_price_stop contract.
  - Staleness, reattribution and rotation gates use the 0-100 TCS scale;
    the risk gate never reads an unbound broker account.

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
        self.settings_books = []


@contextlib.contextmanager
def _desk(*, states, daily_over=frozenset(), verdicts=None,
          coin_veto=None, bias="unknown", rows=None, books=None,
          pass_market=False):
    """Yield (agent, calls). `states` is what check_states returns (a
    dict of real KillSwitch objects, None, or an Exception instance to
    raise). `verdicts` provides each coin_loss_halt book's (halt, reason)
    answer; `coin_veto` is a default for pinned-path tests.

    `books`: {user_id: BotSettings}, both the registered-book list and
    the settings returned for each book. Otherwise registry ids come
    from `states`, or A/B/C for unavailable kill-switch reads. A bare
    settings read fails the test: there is no controlling primary row.

    `pass_market`: the stock market-quality gates (liquidity,
    overextension, spread) answer None and one candle is on the tape,
    so a STOCK signal reaches the approval instead of dying at 'No
    price data'; the cap tier reads 'unknown' (no fundamentals fetch)."""
    calls = _Calls()
    client = _Client(paper_positions=[], paper_accounts=[], profiles=[])
    _books = dict(books or {})
    _registry = sorted(books if books is not None else
                       states if isinstance(states, dict) else ("A", "B", "C"))

    def _gbs(user_id=None, *_a, **_k):
        assert user_id is not None, "risk evaluation must not read primary settings"
        calls.settings_books.append(str(user_id))
        if str(user_id) in _books:
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
        halted, reason = (verdicts or {}).get(str(user_id), (False, ""))
        return reason if halted else coin_veto

    async def _clhb(_client, sym):
        calls.by_book.append(sym)
        raise AssertionError("normalized risk signals must use their own coin-loss book")

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
        agent = rm.RiskManagerAgent()
        agent._registered_books = lambda: set(_registry)
        yield agent, calls


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


def _verdicts(out, expected, *, origin=None):
    """Assert the exact book-to-verdict map; no lost or duplicate books."""
    assert not any(m.kind == "error" for m in out), [(m.kind, m.payload) for m in out]
    verdicts = [m for m in out if m.kind in ("approve", "veto")]
    assert len(verdicts) == len(expected), [(m.kind, m.payload) for m in out]
    actual = {m.payload.get("user_id"): m for m in verdicts}
    assert {uid: m.kind for uid, m in actual.items()} == expected, [
        (m.kind, m.payload) for m in verdicts]
    for uid, verdict in actual.items():
        if verdict.kind == "approve":
            assert verdict.payload.get("book_scoped") is True, (uid, verdict.payload)
            assert "benched_books" not in verdict.payload, (uid, verdict.payload)
            if origin is not None:
                assert verdict.payload.get("origin_book") == origin, (uid, verdict.payload)
    return actual


THREE_OPEN = {"A": _open(), "B": _open(), "C": _open()}


# --- BI-04: the per-coin bench is per book --------------------------------

def test_scanner_crypto_signal_benches_only_the_two_affected_books():
    verdicts = {"A": (True, "XRP per-coin daily loss limit: A"),
                "B": (True, "XRP per-coin daily loss limit: B"), "C": (False, "")}
    with _desk(states=THREE_OPEN, verdicts=verdicts) as (agent, calls):
        results = _verdicts(_run(agent.on_message(_signal())),
                            {"A": "veto", "B": "veto", "C": "approve"})
    for uid in ("A", "B"):
        assert results[uid].payload["reason"] == verdicts[uid][1]
    assert calls.coin_loss_halt == [("XRP", "A"), ("XRP", "B"), ("XRP", "C")]
    assert calls.by_book == [], "each normalized signal must use its own book"


def test_scanner_crypto_signal_with_every_book_benched_is_vetoed():
    verdicts = {uid: (True, f"XRP per-coin daily loss limit: {uid}") for uid in THREE_OPEN}
    with _desk(states=THREE_OPEN, verdicts=verdicts) as (agent, _):
        results = _verdicts(_run(agent.on_message(_signal())),
                            {"A": "veto", "B": "veto", "C": "veto"})
    for uid, result in results.items():
        assert result.payload["reason"] == verdicts[uid][1]


def test_scanner_crypto_signal_approves_each_open_book_without_shared_bench_list():
    with _desk(states=THREE_OPEN, verdicts={}) as (agent, calls):
        _verdicts(_run(agent.on_message(_signal())),
                  {"A": "approve", "B": "approve", "C": "approve"})
    assert calls.by_book == []
    assert calls.coin_loss_halt == [("XRP", "A"), ("XRP", "B"), ("XRP", "C")]


def test_scanner_coin_guards_never_use_the_aggregate_by_book_read():
    with _desk(states=THREE_OPEN, verdicts={}) as (agent, calls):
        _verdicts(_run(agent.on_message(_signal())),
                  {"A": "approve", "B": "approve", "C": "approve"})
    assert calls.by_book == []
    assert calls.coin_loss_halt == [("XRP", "A"), ("XRP", "B"), ("XRP", "C")]


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
    verdicts = {"A": (True, "XRP per-coin daily loss limit: A"),
                "B": (False, ""), "C": (False, "")}
    with _desk(states=THREE_OPEN, verdicts=verdicts) as (agent, calls):
        results = _verdicts(_run(agent.on_message(_signal(user_id="A"))),
                            {"A": "veto", "B": "approve", "C": "approve"}, origin="A")
    assert results["A"].payload["reason"] == verdicts["A"][1]
    assert calls.by_book == []
    assert calls.coin_loss_halt == [("XRP", "A"), ("XRP", "B"), ("XRP", "C")]


def test_provenance_crypto_signal_vetoes_only_the_benched_sibling():
    verdicts = {"A": (False, ""), "B": (True, "XRP per-coin daily loss limit: B"),
                "C": (False, "")}
    with _desk(states=THREE_OPEN, verdicts=verdicts) as (agent, _):
        results = _verdicts(_run(agent.on_message(_signal(user_id="A"))),
                            {"A": "approve", "B": "veto", "C": "approve"}, origin="A")
    assert results["B"].payload["reason"] == verdicts["B"][1]


# --- KS-11: None from check_states is 'cannot evaluate' -------------------

def test_check_states_none_does_not_veto_and_does_not_raise():
    saved = rm._LAST_KS_UNKNOWN_LOG
    try:
        rm._LAST_KS_UNKNOWN_LOG = {}
        with _desk(states=None, verdicts={}) as (agent, calls):
            _verdicts(_run(agent.on_message(_signal())),
                      {"A": "approve", "B": "approve", "C": "approve"})
        assert calls.daily_dollar_over == 0, "no known states -> no dollar brake read"
        assert bool(rm._LAST_KS_UNKNOWN_LOG), "unknown kill-switch state must be logged"
    finally:
        rm._LAST_KS_UNKNOWN_LOG = saved


def test_check_states_raising_is_also_cannot_evaluate():
    saved = rm._LAST_KS_UNKNOWN_LOG
    try:
        rm._LAST_KS_UNKNOWN_LOG = {}
        with _desk(states=RuntimeError("supabase down"), verdicts={}) as (agent, _):
            _verdicts(_run(agent.on_message(_signal())),
                      {"A": "approve", "B": "approve", "C": "approve"})
        assert bool(rm._LAST_KS_UNKNOWN_LOG)
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
        rm._LAST_KS_UNKNOWN_LOG = {}
        with _patched(activity_log, record=lambda *_a, **_k: None):
            rm._note_kill_switch_unknown("XRP")
            first = dict(rm._LAST_KS_UNKNOWN_LOG)
            rm._note_kill_switch_unknown("XRP")
        assert rm._LAST_KS_UNKNOWN_LOG == first, "a veto storm must not become a log storm"
    finally:
        rm._LAST_KS_UNKNOWN_LOG = saved


def test_every_book_hard_halted_is_still_a_veto():
    states = {"A": _halt(), "B": _halt(), "C": _halt()}
    with _desk(states=states, verdicts={}) as (agent, _):
        results = _verdicts(_run(agent.on_message(_signal())),
                            {"A": "veto", "B": "veto", "C": "veto"})
    for uid, result in results.items():
        assert result.payload["reason"].startswith(f"Kill-switch [book {uid}]")


def test_one_halted_book_does_not_veto_the_others():
    with _desk(states={"A": _halt(), "B": _open(), "C": _open()}, verdicts={}) as (agent, _):
        results = _verdicts(_run(agent.on_message(_signal())),
                            {"A": "veto", "B": "approve", "C": "approve"})
    assert results["A"].payload["reason"].startswith("Kill-switch [book A]")


# --- KS-12: the daily $ brake, per book, None on failure ------------------

def test_daily_dollar_over_is_read_from_killswitch_per_book():
    with _desk(states=THREE_OPEN, daily_over={"A"}, verdicts={}) as (agent, calls):
        results = _verdicts(_run(agent.on_message(_signal())),
                            {"A": "veto", "B": "approve", "C": "approve"})
    assert calls.daily_dollar_over == 3, "each book must check its dollar brake"
    assert "daily $ loss limit" in results["A"].payload["reason"]


def test_every_book_over_its_dollar_limit_is_a_veto():
    with _desk(states=THREE_OPEN, daily_over={"A", "B", "C"}, verdicts={}) as (agent, _):
        results = _verdicts(_run(agent.on_message(_signal())),
                            {"A": "veto", "B": "veto", "C": "veto"})
    for uid, result in results.items():
        assert "daily $ loss limit" in result.payload["reason"]
        assert result.payload["reason"].startswith(f"Kill-switch [book {uid}]")


def test_daily_dollar_over_none_is_unknown_not_a_veto():
    with _desk(states=THREE_OPEN, daily_over=None, verdicts={}) as (agent, _):
        _verdicts(_run(agent.on_message(_signal())),
                  {"A": "approve", "B": "approve", "C": "approve"})


def test_the_old_in_module_drawdown_helper_is_gone():
    assert not hasattr(rm, "_users_in_daily_drawdown"), (
        "KS-12: the $ brake lives in killswitch.daily_dollar_over now; a "
        "second copy here would drift")


# --- the outage: a real direction must reach the gates below the bar -----

def test_a_signal_with_a_real_direction_never_raises_unbound_local():
    for direction in ("bullish", "bearish", "long", "short"):
        with _desk(states=THREE_OPEN, bias="unknown", rows=[]) as (agent, calls):
            try:
                out = _run(agent.on_message(_stock(direction=direction)))
            except UnboundLocalError as exc:
                raise AssertionError(f"THE OUTAGE IS BACK for {direction!r}: {exc}")
        results = _verdicts(out, {"A": "veto", "B": "veto", "C": "veto"})
        for uid, result in results.items():
            assert "No price data" in result.payload["reason"], (direction, uid, result.payload)
        assert calls.alpaca_get_account == 0, "risk must not read an unbound broker account"


# --- TE-07: 'long' / 'short' at the market-bias gate ----------------------

def test_long_direction_is_treated_as_long_by_the_market_bias_gate():
    with _desk(states=THREE_OPEN, bias='bearish', rows=[]) as (agent, _):
        results = _verdicts(_run(agent.on_message(_stock(direction='long'))),
                            {"A": "veto", "B": "veto", "C": "veto"})
    for uid, result in results.items():
        assert 'long trades blocked' in result.payload["reason"], (uid, result.payload)


def test_bullish_still_maps_to_long():
    with _desk(states=THREE_OPEN, bias='bearish', rows=[]) as (agent, _):
        results = _verdicts(_run(agent.on_message(_stock(direction='bullish'))),
                            {"A": "veto", "B": "veto", "C": "veto"})
    for uid, result in results.items():
        assert 'long trades blocked' in result.payload["reason"], (uid, result.payload)


def test_short_direction_is_treated_as_short_by_the_market_bias_gate():
    with _desk(states=THREE_OPEN, bias='bullish', rows=[]) as (agent, _):
        results = _verdicts(_run(agent.on_message(_stock(direction='short'))),
                            {"A": "veto", "B": "veto", "C": "veto"})
    for uid, result in results.items():
        assert 'short trades blocked' in result.payload["reason"], (uid, result.payload)


def test_a_short_in_a_bearish_tape_passes_the_bias_gate():
    with _desk(states=THREE_OPEN, bias='bearish', rows=[]) as (agent, _):
        results = _verdicts(_run(agent.on_message(_stock(direction='short'))),
                            {"A": "veto", "B": "veto", "C": "veto"})
    for uid, result in results.items():
        assert 'No price data' in result.payload["reason"], (uid, result.payload)


# --- TE-02 / TE-24: the approve payload -----------------------------------

def test_book_scoped_passes_through_to_the_approval():
    with _desk(states=THREE_OPEN, coin_veto=None) as (agent, _):
        v = _verdict(_run(agent.on_message(_signal(user_id="B", book_scoped=True))))
    assert v.kind == "approve" and v.payload.get("book_scoped") is True, v.payload


def test_unscoped_signal_becomes_one_pinned_approval_per_book():
    with _desk(states=THREE_OPEN, verdicts={}) as (agent, _):
        results = _verdicts(_run(agent.on_message(_signal())),
                            {"A": "approve", "B": "approve", "C": "approve"})
    assert all("origin_book" not in v.payload for v in results.values())


def test_position_pct_is_gone_from_the_approval():
    with _desk(states=THREE_OPEN, verdicts={}) as (agent, _):
        results = _verdicts(_run(agent.on_message(_signal())),
                            {"A": "approve", "B": "approve", "C": "approve"})
    for uid, result in results.items():
        assert "position_pct" not in result.payload, (uid, result.payload)
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


# --- Each book owns its confidence floor ---------------------------------
# With floors 40/70, a shared 55 signal must approve A and veto B before
# execution; origin provenance cannot alter either book's threshold.

TWO_OPEN = {"A": _open(), "B": _open()}


def _two_floors():
    return {"A": settings.BotSettings(tcs_threshold=40),
            "B": settings.BotSettings(tcs_threshold=70)}


def test_unscoped_signal_is_judged_at_each_books_own_floor():
    with _desk(states=TWO_OPEN, books=_two_floors(), pass_market=True) as (agent, calls):
        results = _verdicts(_run(agent.on_message(_stock(tcs=55))),
                            {"A": "approve", "B": "veto"})
    assert "below threshold 70" in results["B"].payload["reason"]
    assert set(calls.settings_books) == {"A", "B"}


def test_unscoped_signal_under_every_floor_is_still_vetoed():
    with _desk(states=TWO_OPEN, books=_two_floors(), pass_market=True) as (agent, _):
        results = _verdicts(_run(agent.on_message(_stock(tcs=35))),
                            {"A": "veto", "B": "veto"})
    for uid, floor in (("A", 40), ("B", 70)):
        assert f"below threshold {floor}" in results[uid].payload["reason"]


def test_user_scoped_signal_keeps_its_own_books_floor():
    with _desk(states=TWO_OPEN, books=_two_floors(), pass_market=True) as (agent, calls):
        results = _verdicts(_run(agent.on_message(_stock(tcs=55, user_id="B", book_scoped=True))),
                            {"B": "veto"})
    assert "below threshold 70" in results["B"].payload["reason"]
    assert set(calls.settings_books) == {"B"}, "pinned signals must not consult siblings"


def test_unavailable_book_registry_vetoes_without_primary_fallback():
    with _desk(states=TWO_OPEN, books=_two_floors(), pass_market=True) as (agent, calls):
        agent._registered_books = lambda: set()
        result = _verdict(_run(agent.on_message(_stock(tcs=55))))
    assert result.kind == "veto" and "Book unavailable" in result.payload["reason"]
    assert "no primary fallback" in result.payload["reason"]
    assert calls.settings_books == [], "unavailable registry must not consult primary settings"


# --- Pinned signals judge exactly their own book --------------------------

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


def test_scanner_signal_judges_halted_and_open_books_separately():
    with _desk(states={"A": _halt(), "B": _open()}, verdicts={}) as (agent, _):
        results = _verdicts(_run(agent.on_message(_signal())), {"A": "veto", "B": "approve"})
    assert results["A"].payload["reason"].startswith("Kill-switch [book A]")


# --- A bare user_id is provenance; every registered book is judged --------

def test_halted_origin_book_does_not_veto_its_open_sibling():
    with _desk(states={"A": _halt(), "B": _open()}, verdicts={}) as (agent, _):
        results = _verdicts(_run(agent.on_message(_signal(user_id="A"))),
                            {"A": "veto", "B": "approve"}, origin="A")
    assert results["A"].payload["reason"].startswith("Kill-switch [book A]")


def test_origin_daily_loss_limit_does_not_veto_its_open_sibling():
    with _desk(states=TWO_OPEN, daily_over={"A"}, verdicts={}) as (agent, _):
        results = _verdicts(_run(agent.on_message(_signal(user_id="A"))),
                            {"A": "veto", "B": "approve"}, origin="A")
    assert "daily $ loss limit" in results["A"].payload["reason"]


def test_recovering_origin_bumps_only_its_own_bar_and_lane_policy():
    with _desk(states={"A": _recovering(), "B": _open()}, verdicts={}) as (agent, _):
        results = _verdicts(_run(agent.on_message(_signal(user_id="A", tcs=40))),
                            {"A": "veto", "B": "approve"}, origin="A")
    assert f"below threshold {35 + ks.RECOVERY_TCS_BUMP}" in results["A"].payload["reason"]
    assert "weekly recovery" in results["A"].payload["reason"]
    with _desk(states={"A": _recovering(), "B": _open()}, verdicts={}) as (agent, _):
        results = _verdicts(_run(agent.on_message(
            _signal(user_id="A", strategy="crypto_scalp", tcs=90))),
            {"A": "veto", "B": "approve"}, origin="A")
    assert "recovery suspends crypto_scalp" in results["A"].payload["reason"]


def test_provenance_stock_signal_from_a_halted_primary_still_reaches_the_siblings():
    with _desk(states={"A": _halt(), "B": _open()}, pass_market=True) as (agent, _):
        results = _verdicts(_run(agent.on_message(_stock(user_id="A"))),
                            {"A": "veto", "B": "approve"}, origin="A")
    assert results["A"].payload["reason"].startswith("Kill-switch [book A]")


def test_provenance_user_id_is_no_free_pass_when_every_book_is_halted():
    with _desk(states={"A": _halt(), "B": _halt()}, verdicts={}) as (agent, _):
        results = _verdicts(_run(agent.on_message(_signal(user_id="A"))),
                            {"A": "veto", "B": "veto"})
    for uid, result in results.items():
        assert result.payload["reason"].startswith(f"Kill-switch [book {uid}]")


def test_pinned_signal_on_a_halted_book_a_is_vetoed_naming_a():
    """The pin still binds: user_id="A" WITH book_scoped while A is
    halted and B is open -> veto naming A, attributed to A."""
    with _desk(states={"A": _halt(), "B": _open()}, coin_veto=None) as (agent, _):
        v = _verdict(_run(agent.on_message(_signal(user_id="A", book_scoped=True))))
    assert v.kind == "veto", v.payload
    assert v.payload["reason"].startswith("Kill-switch [book A]"), v.payload["reason"]
    assert v.payload["user_id"] == "A", v.payload


def test_pinned_signal_missing_or_unknown_book_never_falls_back():
    for uid in (None, "MISSING"):
        with _desk(states=THREE_OPEN) as (agent, calls):
            result = _verdict(_run(agent.on_message(_signal(user_id=uid, book_scoped=True))))
        assert result.kind == "veto", result.payload
        assert "Book unavailable" in result.payload["reason"], result.payload
        assert "no primary fallback" in result.payload["reason"]
        assert calls.settings_books == [], "invalid pin must not read account settings"
        assert calls.coin_loss_halt == [], "invalid pin must not evaluate another book"


def test_provenance_preserves_an_existing_origin_book():
    with _desk(states=TWO_OPEN) as (agent, _):
        _verdicts(_run(agent.on_message(_signal(origin_book="RESEARCH"))),
                  {"A": "approve", "B": "approve"}, origin="RESEARCH")


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
        results = _verdicts(_run(agent.on_message(_ladder())),
                            {"A": "approve", "B": "approve"}, origin="B")
    for uid, result in results.items():
        assert result.payload.get("no_price_stop") is True, uid
        assert "stop_pct" not in result.payload and "target_pct" not in result.payload, uid
        assert result.payload.get("max_notional") == 420.0, uid
        assert "no price stop" in result.payload["thesis"]["exit_watch"], uid


def test_the_same_signal_without_the_flag_still_gets_the_default_stop():
    message = _ladder()
    message.payload.pop("no_price_stop")
    with _desk(states=TWO_OPEN, pass_market=True) as (agent, _):
        results = _verdicts(_run(agent.on_message(message)),
                            {"A": "approve", "B": "approve"}, origin="B")
    for uid, result in results.items():
        assert "no_price_stop" not in result.payload, uid
        assert result.payload.get("stop_pct") == 0.05, (uid, result.payload)


def test_no_price_stop_wins_over_a_stop_the_producer_also_sent():
    with _desk(states=TWO_OPEN, pass_market=True) as (agent, _):
        results = _verdicts(_run(agent.on_message(_ladder(stop_pct=0.03, target_pct=0.09))),
                            {"A": "approve", "B": "approve"}, origin="B")
    for uid, result in results.items():
        assert result.payload.get("no_price_stop") is True, uid
        assert "stop_pct" not in result.payload and "target_pct" not in result.payload, uid


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
