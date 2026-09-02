"""TC-05 (audit 2026-09-01): drive the REAL AdaptiveScopeAgent.on_message.

Adaptive Scope is the agent that turns a Market Sentiment / Research
`event` into a ticker flag the Risk Manager vetoes on. Until now nothing
in the deploy gate executed its handler -- a change that broke the
suggest/guarded/full split, or that flagged a ticker on a positive
headline, would have shipped green.

These tests load the real module through _bootstrap (stub config, no
.env, no network) and call on_message with real AgentMessage objects.
Only the seams are swapped, each one restored: the autonomy-mode read
(a Supabase-backed bot_settings row), the best-effort Supabase persist,
and the process-wide scope_state (swapped for a fresh instance of the
REAL _ScopeState class so the tests never mutate the shared one).
event_adjustment, the guardrails, the flag cap and the message shapes
are the real code.

Run: python -m tests.run_all   (from agents/)
 or: python -m tests.test_adaptive_scope_handler
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _bootstrap import load_module, run_tests, stub_config  # noqa: E402

stub_config()
base = load_module("app.agents.base")
scope = load_module("app.runtime.scope")
adaptive = load_module("app.strategies.adaptive")
settings_mod = load_module("app.runtime.settings")
asa = load_module("app.agents.adaptive_scope")

AgentMessage = base.AgentMessage


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@contextlib.contextmanager
def _patched(mod, **attrs):
    """Swap module attributes and always put the originals back (sentinel
    restore, so a real attribute whose value is None is restored, not
    deleted). run_all imports every suite into ONE process."""
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


@contextlib.contextmanager
def _desk(mode="guarded"):
    """The real agent with its three seams swapped and restored:
    autonomy mode pinned, persist recorded, scope_state fresh."""
    persisted = []
    state = scope._ScopeState()          # the REAL class, a private instance

    async def _persist(adj):
        persisted.append(adj)

    with _patched(asa, _autonomy_mode=lambda: mode, _persist=_persist,
                  scope_state=state):
        yield asa.AdaptiveScopeAgent(), state, persisted


def _event(**over):
    p = {"ticker": "TSLA", "event_type": "legal", "severity": "high",
         "sentiment": "negative", "headline": "DOJ opens probe"}
    p.update(over)
    return AgentMessage(agent="market_sentiment", kind="event", payload=p)


# --- kind gate --------------------------------------------------------------

def test_non_event_messages_are_ignored_and_touch_nothing():
    with _desk("full") as (agent, state, persisted):
        for kind in ("signal", "approve", "execute", "info", "scope"):
            out = _run(agent.on_message(AgentMessage(
                agent="x", kind=kind, payload={"ticker": "TSLA",
                                               "severity": "high",
                                               "event_type": "legal"})))
            assert out == [], kind
    assert persisted == []
    assert state.view().flagged_tickers == frozenset()


# --- guarded mode (the default) ----------------------------------------------

def test_guarded_flags_a_high_severity_event_and_says_so():
    with _desk("guarded") as (agent, state, persisted):
        out = _run(agent.on_message(_event()))
        assert len(out) == 1
        m = out[0]
        assert m.kind == "scope", m
        assert m.agent == "adaptive_scope"
        assert m.payload["action"] == "flag_ticker"
        assert m.payload["scope"] == "TSLA"
        assert m.payload["trigger"] == "event:legal"
        assert "Risk Manager will veto" in m.payload["note"]
        # the flag really landed where the Risk Manager reads it
        assert "TSLA" in state.view().flagged_tickers
        assert [a.status for a in persisted] == ["applied"]
        assert persisted[0].scope == "TSLA"


def test_guarded_ignores_a_low_severity_event():
    """Guarded acts on medium/high only; low is a no-op with no persist."""
    with _desk("guarded") as (agent, state, persisted):
        out = _run(agent.on_message(_event(severity="low")))
    assert out == []
    assert persisted == []
    assert state.view().flagged_tickers == frozenset()


def test_guarded_acts_on_medium_severity():
    with _desk("guarded") as (agent, state, _):
        out = _run(agent.on_message(_event(severity="medium")))
        assert out and out[0].kind == "scope"
        assert "TSLA" in state.view().flagged_tickers


def test_a_positive_headline_is_not_a_reason_to_flag():
    with _desk("full") as (agent, state, persisted):
        out = _run(agent.on_message(_event(sentiment="positive",
                                           event_type="guidance")))
        assert out == []
        assert state.view().flagged_tickers == frozenset()
        # ...except upcoming earnings, binary risk either way
        out = _run(agent.on_message(_event(sentiment="positive",
                                           event_type="earnings_upcoming")))
        assert out and out[0].kind == "scope"
        assert "TSLA" in state.view().flagged_tickers
    assert len(persisted) == 1


def test_an_event_type_outside_the_flaggable_set_is_ignored():
    with _desk("full") as (agent, state, persisted):
        out = _run(agent.on_message(_event(event_type="product_launch")))
    assert out == [] and persisted == []
    assert state.view().flagged_tickers == frozenset()


def test_a_tickerless_event_is_ignored():
    with _desk("full") as (agent, state, persisted):
        out = _run(agent.on_message(_event(ticker="")))
    assert out == [] and persisted == []


# --- full mode ----------------------------------------------------------------

def test_full_also_acts_on_low_severity():
    with _desk("full") as (agent, state, persisted):
        out = _run(agent.on_message(_event(severity="low",
                                           event_type="leadership")))
        assert len(out) == 1 and out[0].kind == "scope"
        assert out[0].payload["trigger"] == "event:leadership"
        assert "TSLA" in state.view().flagged_tickers
        assert persisted and persisted[0].severity == "low"


def test_the_flag_is_upper_cased_so_the_risk_manager_matches_it():
    with _desk("full") as (agent, state, _):
        _run(agent.on_message(_event(ticker="nvda")))
        assert "NVDA" in state.view().flagged_tickers


# --- suggest mode: record, change nothing ------------------------------------

def test_suggest_records_the_proposal_and_applies_nothing():
    with _desk("suggest") as (agent, state, persisted):
        out = _run(agent.on_message(_event()))
        assert len(out) == 1
        m = out[0]
        assert m.kind == "info", "suggest mode must not emit a scope change"
        assert "awaiting approval" in m.payload["note"]
        assert m.payload["action"] == "flag_ticker" and m.payload["scope"] == "TSLA"
        assert state.view().flagged_tickers == frozenset(), (
            "suggest mode flagged a ticker -- that is guarded's job")
        assert [a.status for a in persisted] == ["suggested"]


# --- the cap ------------------------------------------------------------------

def test_the_flag_cap_is_reported_not_silently_dropped():
    with _desk("full") as (agent, state, persisted):
        for i in range(adaptive.MAX_FLAGGED_TICKERS):
            out = _run(agent.on_message(_event(ticker=f"T{i:02d}")))
            assert out[0].kind == "scope", i
        assert len(state.view().flagged_tickers) == adaptive.MAX_FLAGGED_TICKERS
        out = _run(agent.on_message(_event(ticker="ONEMORE")))
        assert len(out) == 1 and out[0].kind == "info"
        assert "cap reached" in out[0].payload["note"]
        assert "ONEMORE" not in state.view().flagged_tickers
        # a ticker already flagged refreshes rather than counting against the cap
        out = _run(agent.on_message(_event(ticker="T00")))
        assert out[0].kind == "scope"
    assert len(persisted) == adaptive.MAX_FLAGGED_TICKERS + 2


# --- the autonomy-mode read itself -------------------------------------------

def test_autonomy_mode_reads_the_settings_row_and_defaults_to_guarded_on_failure():
    """Drive the REAL _autonomy_mode: it late-imports
    app.runtime.settings.get_bot_settings, so the module attribute is the
    seam. A row that says 'full' is honoured; a failing read (Supabase
    down at boot) falls back to guarded, never to full."""
    class _Row:
        autonomy_mode = "full"

    with _patched(settings_mod, get_bot_settings=lambda *a, **k: _Row()):
        assert asa._autonomy_mode() == "full"

    class _Blank:
        autonomy_mode = ""

    with _patched(settings_mod, get_bot_settings=lambda *a, **k: _Blank()):
        assert asa._autonomy_mode() == "guarded"

    def _boom(*a, **k):
        raise RuntimeError("supabase unreachable")

    with _patched(settings_mod, get_bot_settings=_boom):
        assert asa._autonomy_mode() == "guarded"


def test_on_message_uses_the_live_mode_read_end_to_end():
    """No _autonomy_mode stub: pin the settings row instead, so the path
    settings row -> _autonomy_mode -> event_adjustment -> scope_state is
    the real one from top to bottom."""
    class _Row:
        autonomy_mode = "suggest"

    persisted = []
    state = scope._ScopeState()

    async def _persist(adj):
        persisted.append(adj)

    with _patched(settings_mod, get_bot_settings=lambda *a, **k: _Row()), \
            _patched(asa, _persist=_persist, scope_state=state):
        out = _run(asa.AdaptiveScopeAgent().on_message(_event()))
    assert out and out[0].kind == "info" and "awaiting approval" in out[0].payload["note"]
    assert state.view().flagged_tickers == frozenset()
    assert [a.status for a in persisted] == ["suggested"]


def test_zz_shared_scope_state_was_never_touched():
    """Sorted last: the process-wide scope_state the Risk Manager reads
    must be exactly as it was before this suite -- no flags, no posture."""
    assert asa.scope_state is scope.scope_state, "scope_state seam not restored"
    assert scope.scope_state.view().flagged_tickers == frozenset()
    assert scope.scope_state.current_posture() is None


if __name__ == "__main__":
    sys.exit(run_tests(dict(globals())))
