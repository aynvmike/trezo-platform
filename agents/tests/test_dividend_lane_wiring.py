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
  TE-06  the lane's activation switch: the signal carries `tcs` if and
         only if Settings.trezo_dividend_lt_tcs is > 0 (TREZO_DIVIDEND_LT_TCS
         in agents/.env). At 0 the lane stays dark exactly as before;
         no_price_stop and max_notional ride on every signal either way.

Plain zero-arg test_ functions, no pytest, no fixtures, no network, no
.env -- this file must run under tests/run_all.py.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _bootstrap import load_module, run_tests, stub_config  # noqa: E402

stub_config()
agent_mod = load_module("app.agents.dividend_lt_agent")
screen_mod = load_module("app.strategies.dividend_screen")
universe_mod = load_module("app.data.market_universe")
kb = load_module("app.payments.kindrip_bridge")


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


def _tick(positions, pool, verdicts, screen=_no_screen):
    client = _Client({"paper_positions": _Res(positions)})
    agent = agent_mod.DividendLTAgent()
    agent._last_states = {}
    with _patched(agent_mod, screen_many=_screen_many(verdicts)), \
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


def test_ladder_signal_carries_tcs_iff_the_switch_is_on():
    """tcs present <=> Settings.trezo_dividend_lt_tcs > 0. The dark cases
    (0, absent, junk, negative) must leave NO tcs key -- Risk Manager
    reads payload.get('tcs', 0), so the lane stays dark exactly as it
    did before the switch existed."""
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
                assert "tcs" not in m.payload, (cfg.__dict__, m.payload)
            else:
                assert m.payload["tcs"] == want, (cfg.__dict__, m.payload)
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
    assert "trezo_dividend_lt_tcs: int = 0" in cfg, (
        "Settings has no trezo_dividend_lt_tcs field -- the switch is dead")
    src = Path(agent_mod.__file__).read_text(encoding="utf-8", errors="replace")
    assert 'getattr(get_settings(), "trezo_dividend_lt_tcs", 0)' in src
    assert "TREZO_DIVIDEND_LT_TCS" in src, "the switch is not documented"


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
            _patched(universe_mod, market_wide_candidates=_pool()), \
            _patched(screen_mod, screen=_no_screen):
        _run(agent._tick_book(client, "book-1", dict(_ROW)))
    cols = [c for t, c in client.selects if t == "paper_positions"]
    assert cols and "strategy" in cols[0], cols


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
