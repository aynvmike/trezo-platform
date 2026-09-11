"""Wiring guards for the Dividends (Long-Term) lane agent -- and the
KINDRIP bridge's parent-name read (audit 2026-09-01: TE-07, MIG-02).

BUILT BUT NOT BOUND is the house failure mode, so these drive the real
`_tick_book` with a fake Supabase client rather than asserting on a
constant, and check what actually leaves the agent on the bus.

  TE-07  the ladder signal said direction='long'. Trade Execution maps
         ONLY 'bullish' to a long, so the lane's first entry would have
         been routed as a SHORT of a dividend grower.
  TE-07  every open position counted as a ladder name, so a book with a
         few ordinary stock positions read as a full ladder and the lane
         never proposed anything.
  MIG-02 the KINDRIP bridge selected profiles.full_name/email, neither
         of which exists; the error was swallowed and every draft
         instruction was stamped 'Trezo Parent'.
  TE-06  legacy configured scores stay labelled; unset values now use
         measured entry confidence after the quality screen. Missing
         holdings/data fail closed; no_price_stop and max_notional ride
         on every signal either way.
  vf:no-price-stop-exec (skeptic 2026-09-01): every ladder signal is
         pinned to ITS book (book_scoped True). Trade Execution treats a
         bare user_id as provenance and fans the approval out to every
         book, so without the pin one book's per-name cap would buy the
         name on all three.

Plain zero-arg test_ functions, no pytest, no fixtures, no network, no
.env -- this file must run under tests/run_all.py.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _bootstrap import load_module, run_tests, stub_config  # noqa: E402

stub_config()
agent_mod = load_module("app.agents.dividend_lt_agent")
screen_mod = load_module("app.strategies.dividend_screen")
universe_mod = load_module("app.data.market_universe")
kb = load_module("app.payments.kindrip_bridge")
allocation = load_module("app.paper.allocation")
settings = load_module("app.runtime.settings")


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@contextlib.contextmanager
def _patched(mod, **attrs):
    """Swap module attributes for the duration of a test and restore them
    -- never plants anything in sys.modules."""
    missing = object()
    old = {k: getattr(mod, k, missing) for k in attrs}
    try:
        for k, v in attrs.items():
            setattr(mod, k, v)
        yield
    finally:
        for k, v in old.items():
            if v is missing:
                delattr(mod, k)
            else:
                setattr(mod, k, v)


# --- fake Supabase: just enough of the builder chain for _tick_book ------

class _Res:
    def __init__(self, data, error=None):
        self.data = data
        self.error = error


class _Query:
    def __init__(self, client, table):
        self._client = client
        self._table = table
        self.selected = None

    def select(self, cols):
        self.selected = cols
        self._client.selects.append((self._table, cols))
        return self

    def eq(self, *_a):
        return self

    def gt(self, *_a):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        return self._client.responses.get(self._table, _Res([]))


class _Client:
    def __init__(self, responses):
        self.responses = responses
        self.selects = []

    def table(self, name):
        return _Query(self, name)


def _verdict(ticker, sector):
    return screen_mod.ScreenResult(
        ticker=ticker, passed=True, tier="GROWTH", yield_pct=0.03,
        payout_ratio=0.45, raise_streak_years=12, sector=sector)


def _pool(*tickers):
    async def _mw(limit=80):
        return list(tickers)
    return _mw


def _screen_many(verdicts):
    async def _sm(tickers, **_k):
        return {t: verdicts[t] for t in tickers if t in verdicts}
    return _sm


async def _no_screen(_ticker, **_k):
    raise AssertionError("graduation screen must not run on non-ladder names")


# income pocket $3,000 -> ladder capital 0.70 * 3000 = 2100 -> 2 ladder names
_ROW = {"allocation_overrides": {"income": 3000, "stocks": 0, "options": 0},
        "dividend_lane_mode": "ACCUMULATE"}


async def _zero_equity(uid):
    return 0.0  # explicit overrides fund the fixture, never a broker read


async def _measured73(ticker, cfg):
    return SimpleNamespace(tcs=73, direction="bullish", breakdown={"trend": 12})


def _tick(positions, pool, verdicts, screen=_no_screen):
    client = _Client({"paper_positions": _Res(positions)})
    agent = agent_mod.DividendLTAgent()
    agent._last_states = {}
    with _patched(agent_mod, screen_many=_screen_many(verdicts),
                  _measured_entry_score=_measured73), \
            _patched(allocation, effective_equity=_zero_equity), \
            _patched(settings, get_bot_settings=lambda uid: settings.BotSettings()), \
            _patched(universe_mod, market_wide_candidates=_pool(*pool)), \
            _patched(screen_mod, screen=screen):
        return _run(agent._tick_book(client, "book-1", dict(_ROW)))


def _signals(msgs):
    return [m for m in msgs if m.kind == "signal"]


# --- TE-07: direction vocabulary -------------------------------------------

def test_ladder_signal_direction_is_bullish_not_long():
    verdicts = {"PG": _verdict("PG", "Staples"), "JNJ": _verdict("JNJ", "Health")}
    out = _tick([], ["PG", "JNJ"], verdicts)
    sigs = _signals(out)
    assert sigs, f"no signal left the agent: {[m.payload for m in out]}"
    for m in sigs:
        assert m.payload["direction"] == "bullish", m.payload["direction"]
        assert m.payload["direction"] != "long"
        assert m.payload["strategy"] == "dividend_lt"
        assert m.payload["asset_type"] == "stock"
        assert m.payload["no_price_stop"] is True
        assert m.payload["user_id"] == "book-1"


# --- TE-06: the activation switch ------------------------------------------

class _Cfg:
    """A stand-in for the pydantic Settings object: only the attributes
    a case sets exist on it, so 'field absent' is a real case."""
    def __init__(self, **kw):
        self.__dict__.update(kw)


def test_ladder_uses_measured_tcs_when_legacy_override_is_unset():
    """Unset/junk legacy values must reach measured scoring, not TCS 0."""
    verdicts = {"PG": _verdict("PG", "Staples")}
    cases = [
        (_Cfg(trezo_dividend_lt_tcs=0), None),
        (_Cfg(), None),                                  # older config
        (_Cfg(trezo_dividend_lt_tcs=None), None),
        (_Cfg(trezo_dividend_lt_tcs="junk"), None),
        (_Cfg(trezo_dividend_lt_tcs=-5), None),
        (_Cfg(trezo_dividend_lt_tcs=60), 60),
        (_Cfg(trezo_dividend_lt_tcs="55"), 55),          # env strings
    ]
    for cfg, want in cases:
        with _patched(agent_mod, get_settings=lambda cfg=cfg: cfg):
            out = _tick([], ["PG"], verdicts)
        sigs = _signals(out)
        assert sigs, f"no signal left the agent for {cfg.__dict__}"
        for m in sigs:
            if want is None:
                assert m.payload["tcs"] == 73, (cfg.__dict__, m.payload)
                assert m.payload["tcs_source"] == "measured_pattern_score"
            else:
                assert m.payload["tcs"] == want, (cfg.__dict__, m.payload)
                assert m.payload["tcs_source"] == "legacy_configured_score"
            assert m.confidence == m.payload["tcs"] / 100.0
            # The contract rides on every signal, switch or no switch.
            assert m.payload["no_price_stop"] is True, m.payload
            assert m.payload["max_notional"] > 0, m.payload
            assert m.payload["strategy"] == "dividend_lt"


def test_the_switch_is_a_real_settings_field_read_by_name():
    """BUILT BUT NOT BOUND guard: _lane_tcs reads
    Settings.trezo_dividend_lt_tcs; the pydantic field must exist so
    TREZO_DIVIDEND_LT_TCS in agents/.env actually reaches it."""
    cfg = (Path(__file__).resolve().parents[1] / "app/config.py").read_text(
        encoding="utf-8", errors="replace")
    # vf:config-web: Optional, default None (= unset -> _lane_tcs reads 0),
    # so a blank TREZO_DIVIDEND_LT_TCS= pasted from the template cannot
    # stop the engine booting.
    assert "trezo_dividend_lt_tcs: int | None = None" in cfg, (
        "Settings has no Optional trezo_dividend_lt_tcs field -- the switch is dead or a boot trap")
    src = Path(agent_mod.__file__).read_text(encoding="utf-8", errors="replace")
    assert 'getattr(get_settings(), "trezo_dividend_lt_tcs", 0)' in src
    assert "TREZO_DIVIDEND_LT_TCS" in src, "the switch is not documented"


def test_the_documented_example_switch_value_clears_the_default_tcs_floor():
    """vf:no-price-stop-exec: the module docstring used to suggest
    TREZO_DIVIDEND_LT_TCS=60, below the default tcs_threshold of 70 --
    a switch that turns the lane on and then has Risk Manager veto every
    signal. The example must clear the default floor and say so."""
    import re as _re
    src = Path(agent_mod.__file__).read_text(encoding="utf-8", errors="replace")
    m = _re.search(r"TREZO_DIVIDEND_LT_TCS=([0-9]+)", src)
    assert m, "the docstring no longer shows an example TREZO_DIVIDEND_LT_TCS value"
    assert int(m.group(1)) > 70, f"example {m.group(1)} does not exceed the default tcs_threshold 70"
    assert "tcs_threshold" in src, "the docstring must say the value has to exceed the book's tcs_threshold"


# --- vf:no-price-stop-exec: the ladder signal is pinned to its book ----------

def test_ladder_signal_is_book_scoped():
    """Drives the real _tick_book: every ladder signal that leaves the
    agent carries book_scoped True next to its user_id, switch on or off.
    trade_execution.on_message treats user_id WITHOUT book_scoped as
    provenance and fans the approval out to every book at this book's
    per-name cap; risk_manager passes book_scoped through to the approval
    (TE-02). Absent or False here and the pin is gone for all of them."""
    verdicts = {"PG": _verdict("PG", "Staples"), "JNJ": _verdict("JNJ", "Health")}
    for cfg in (_Cfg(trezo_dividend_lt_tcs=None), _Cfg(trezo_dividend_lt_tcs=75)):
        with _patched(agent_mod, get_settings=lambda cfg=cfg: cfg):
            out = _tick([], ["PG", "JNJ"], verdicts)
        sigs = _signals(out)
        assert len(sigs) == 2, [m.payload for m in out]
        for m in sigs:
            assert m.payload.get("book_scoped") is True, m.payload
            assert m.payload["user_id"] == "book-1", m.payload
            assert m.payload["no_price_stop"] is True, m.payload


# --- TE-07: ladder count ----------------------------------------------------

def test_ordinary_stock_positions_do_not_fill_the_ladder():
    """Two momentum positions used to read as a 2/2 ladder; the lane then
    never added a name. They are not ladder names."""
    positions = [
        {"ticker": "NVDA", "quantity": 10, "asset_type": "stock",
         "strategy": "momentum"},
        {"ticker": "AMD", "quantity": 5, "asset_type": "stock",
         "strategy": "swing"},
    ]
    verdicts = {"PG": _verdict("PG", "Staples"), "JNJ": _verdict("JNJ", "Health")}
    out = _tick(positions, ["PG", "JNJ"], verdicts)
    assert len(_signals(out)) == 2, [m.payload for m in out]
    scan = [m for m in out if m.payload.get("event") == "dividend_lt_scan"]
    assert scan and "ladder 0/2" in scan[0].payload["note"], scan


def test_dividend_lt_positions_do_count_against_the_ladder():
    positions = [
        {"ticker": "KO", "quantity": 3, "asset_type": "stock",
         "strategy": "dividend_lt"},
        {"ticker": "NVDA", "quantity": 10, "asset_type": "stock",
         "strategy": "momentum"},
    ]
    verdicts = {"PG": _verdict("PG", "Staples"), "JNJ": _verdict("JNJ", "Health"),
                "KO": _verdict("KO", "Staples")}

    async def _ok_screen(_t, **_k):
        return verdicts["KO"]

    out = _tick(positions, ["PG", "JNJ"], verdicts, screen=_ok_screen)
    # ladder 1/2 -> room for exactly one more.
    assert len(_signals(out)) == 1, [m.payload for m in out]


def test_any_held_name_is_still_excluded_from_candidates():
    """`held` is every holding on purpose: the lane must not buy a name
    the book already owns under another strategy."""
    positions = [
        {"ticker": "PG", "quantity": 10, "asset_type": "stock",
         "strategy": "momentum"},
    ]
    verdicts = {"PG": _verdict("PG", "Staples"), "JNJ": _verdict("JNJ", "Health")}
    out = _tick(positions, ["PG", "JNJ"], verdicts)
    tickers = [m.payload["ticker"] for m in _signals(out)]
    assert "PG" not in tickers, tickers
    assert tickers == ["JNJ"], tickers


def test_ladder_count_reads_strategy_column():
    """The positions query must SELECT strategy, or the filter is blind."""
    client = _Client({"paper_positions": _Res([])})
    agent = agent_mod.DividendLTAgent()
    with _patched(agent_mod, screen_many=_screen_many({})), \
            _patched(allocation, effective_equity=_zero_equity), \
            _patched(settings, get_bot_settings=lambda uid: settings.BotSettings()), \
            _patched(universe_mod, market_wide_candidates=_pool()), \
            _patched(screen_mod, screen=_no_screen):
        _run(agent._tick_book(client, "book-1", dict(_ROW)))
    cols = [c for t, c in client.selects if t == "paper_positions"]
    assert cols and "strategy" in cols[0], cols


def test_default_income_budget_comes_from_the_books_existing_allocation():
    for equity, posture in ((10000, "auto"), (75000, "balanced"), (150000, "income")):
        inp = agent_mod._lane_inputs_for({"account_posture": posture}, equity)
        expected = allocation.build_allocation(equity, posture_setting=posture)
        assert inp is not None and inp.capital == expected.budgets["income"]
    assert agent_mod._lane_inputs_for({"allocation_overrides": {"income": 0}}, 150000) is None


def test_real_ladder_tick_uses_measured_score_and_independent_default_budgets():
    # Actual chart scorer, confluence and signal generation; only I/O is fake.
    from tests.test_directional_scoring import _fixture, _mirror
    candles_mod = load_module("app.data.candles")
    verdicts = {"PG": _verdict("PG", "Staples")}
    up = _fixture()
    equity_reads = []
    selected = {"bars": up}

    async def equity(uid):
        equity_reads.append(uid)
        return 10000 if uid == "book-large" else 4000

    async def candles(ticker, asset_type):
        assert (ticker, asset_type) == ("PG", "stock")
        return selected["bars"]

    def cfg(uid):
        return settings.BotSettings(dividend_lt_enabled=(uid != "book-disabled"),
                                    tcs_threshold=80)

    client = _Client({"paper_positions": _Res([])})
    agent = agent_mod.DividendLTAgent()
    agent._last_states = {}
    with _patched(agent_mod, screen_many=_screen_many(verdicts), get_settings=lambda: _Cfg()), \
            _patched(allocation, effective_equity=equity), \
            _patched(settings, get_bot_settings=cfg), \
            _patched(universe_mod, market_wide_candidates=_pool("PG")), \
            _patched(candles_mod, fetch_candles_for=candles):
        large = _run(agent._tick_book(client, "book-large", {}))
        small = _run(agent._tick_book(client, "book-small", {}))
        disabled = _run(agent._tick_book(client, "book-disabled", {}))
        selected["bars"] = _mirror(up)
        bearish = _run(agent._tick_book(client, "book-large", {}))
    signal = _signals(large)[0]
    # Measured 70 remains 70 even when the book's risk threshold is 80.
    assert signal.payload["tcs"] == 70 and signal.confidence == 0.7
    assert signal.payload["tcs_source"] == "measured_pattern_score"
    assert signal.payload["dividend_lt"]["quality_screen_passed"] is True
    assert signal.payload["no_price_stop"] is signal.payload["book_scoped"] is True
    assert signal.payload["user_id"] == "book-large"
    assert not _signals(small) and small[0].payload["reason"] == "income_budget_or_lane_inputs"
    assert not _signals(disabled) and disabled[0].payload["reason"] == "disabled_for_book"
    assert not _signals(bearish) and bearish[0].payload["reason"] == "no_bullish_setup"
    assert equity_reads == ["book-large", "book-small", "book-large"]


def test_failed_or_missing_position_read_never_proposes_a_ladder_buy():
    class BoomClient(_Client):
        def table(self, name):
            raise RuntimeError("position service unavailable")

    clients = [BoomClient({}), _Client({"paper_positions": _Res(None)}),
               _Client({"paper_positions": _Res([], error="read failed")})]
    for client in clients:
        with _patched(allocation, effective_equity=_zero_equity), \
                _patched(settings, get_bot_settings=lambda uid: settings.BotSettings()):
            result = _run(agent_mod.DividendLTAgent()._tick_book(client, "book-1", dict(_ROW)))
        assert not _signals(result)
        assert result[0].payload["reason"] == "position_read_failed"
        assert result[0].payload["user_id"] == "book-1"


def test_unverified_book_settings_block_before_equity_or_holdings_are_read():
    async def forbidden_equity(uid):
        raise AssertionError("fallback settings must stop before reading equity")

    class NoReadsClient(_Client):
        def table(self, name):
            raise AssertionError("fallback settings must stop before reading holdings")

    # Use the real fallback identity check, not a fake disabled book. Its
    # permissive default flags must never become permission to buy.
    fallback = settings._DEFAULTS
    assert settings.is_fallback_settings(fallback)
    with _patched(settings, get_bot_settings=lambda uid: fallback), \
            _patched(allocation, effective_equity=forbidden_equity):
        result = _run(agent_mod.DividendLTAgent()._tick_book(
            NoReadsClient({}), "book-unknown", dict(_ROW)))
    assert not _signals(result)
    assert result[0].payload["reason"] == "settings_unverified"
    assert result[0].payload["user_id"] == "book-unknown"


def test_missing_chart_data_is_an_explicit_block_without_a_score():
    candles_mod = load_module("app.data.candles")
    verdicts = {"PG": _verdict("PG", "Staples")}

    async def missing(*args):
        return []

    with _patched(agent_mod, screen_many=_screen_many(verdicts), get_settings=lambda: _Cfg()), \
            _patched(allocation, effective_equity=_zero_equity), \
            _patched(settings, get_bot_settings=lambda uid: settings.BotSettings()), \
            _patched(universe_mod, market_wide_candidates=_pool("PG")), \
            _patched(candles_mod, fetch_candles_for=missing):
        out = _run(agent_mod.DividendLTAgent()._tick_book(
            _Client({"paper_positions": _Res([])}), "book-1", dict(_ROW)))
    assert not _signals(out)
    assert out[0].payload["reason"] == "scoring_unavailable"
    assert "tcs" not in out[0].payload


# --- MIG-02: KINDRIP parent name --------------------------------------------

class _LogRec:
    def __init__(self):
        self.warnings = []

    def warning(self, event, **kw):
        self.warnings.append((event, kw))

    def info(self, *_a, **_k):
        pass


def test_kindrip_parent_name_comes_from_display_name():
    client = _Client({"profiles": _Res({"display_name": "Mike"})})
    name = _run(kb._parent_name(client, "user-1"))
    assert name == "Mike", name
    cols = [c for t, c in client.selects if t == "profiles"]
    assert cols == ["display_name"], cols
    assert "full_name" not in cols[0] and "email" not in cols[0]


def test_kindrip_placeholder_only_when_display_name_is_empty():
    for row in ({"display_name": ""}, {"display_name": "   "},
                {"display_name": None}, None):
        client = _Client({"profiles": _Res(row)})
        assert _run(kb._parent_name(client, "user-1")) == "Trezo Parent", row


def test_kindrip_parent_name_read_failure_is_logged_not_swallowed():
    rec = _LogRec()
    # A PostgREST error surfaced on the response...
    client = _Client({"profiles": _Res(None, error={"message": "column x"})})
    with _patched(kb, log=rec):
        assert _run(kb._parent_name(client, "user-1")) == "Trezo Parent"
    assert rec.warnings and rec.warnings[0][0] == "kindrip_bridge.parent_name_failed"

    # ...and one raised by the client.
    class _Boom(_Client):
        def table(self, name):
            raise RuntimeError("boom")

    rec = _LogRec()
    with _patched(kb, log=rec):
        assert _run(kb._parent_name(_Boom({}), "user-1")) == "Trezo Parent"
    assert rec.warnings and "boom" in rec.warnings[0][1]["error"]


if __name__ == "__main__":
    sys.exit(run_tests(dict(globals())))
