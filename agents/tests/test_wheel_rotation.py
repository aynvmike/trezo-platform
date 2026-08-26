"""Guards for wheel-universe ordering and the dailies' regime read.

THE BUG THESE PIN (2026-08-25). Mike: "the options are looking quite
the same market pool as before, a lot of Ford and AGNC." Cause: the
universe sort ranked the curated seed above every market-wide name,
then alphabetized WITHIN the seed -- which silently undid the
2026-07-16 seed rotation. With 1-3 CSP slots and cheap names winning
the affordability check, alphabetical order made AGNC the permanent
front of the queue. A fix that ships and is then re-sorted to death is
worse than no fix: it reads as "rotation exists" to everyone who looks.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.relay_ingest import parse_market_regime  # noqa: E402
from app.strategies.wheel_universe import WheelCandidate, _ordered  # noqa: E402


def _c(t, source="seed"):
    return WheelCandidate(ticker=t, source=source, yield_pct=0.05)


# --- ordering ------------------------------------------------------------

def test_rotation_survives_and_actually_rotates():
    cands = [_c(t) for t in ("AGNC", "F", "MO", "T")]
    day1 = [c.ticker for c in _ordered(cands, ordinal=100)]
    day2 = [c.ticker for c in _ordered(cands, ordinal=101)]
    assert day1 != day2, "consecutive days produced the same order"
    assert day1[1:] + day1[:1] == day2, "not a rotation, a shuffle"


def test_alphabetical_head_is_not_permanent():
    """AGNC must not lead every day just for starting with A."""
    cands = [_c(t) for t in ("AGNC", "F", "MO", "T")]
    heads = {_ordered(cands, ordinal=d)[0].ticker for d in range(4)}
    assert heads == {"AGNC", "F", "MO", "T"}, \
        f"only {heads} ever reached the head of the queue"


def test_market_wide_names_share_the_bench_with_the_seed():
    """The seed must not permanently outrank market-wide candidates --
    that is a whitelist wearing a market-wide costume."""
    cands = [_c("AGNC", "seed"), _c("F", "seed"),
             _c("JPM", "market_wide"), _c("XOM", "market_wide")]
    lead_sources = set()
    for d in range(4):
        lead = _ordered(cands, ordinal=d)[0]
        lead_sources.add(lead.source)
    assert "market_wide" in lead_sources, \
        "a market-wide name never reached the head of the queue"


def test_positions_always_come_first():
    """Open positions carry obligations (expiries, assignment) and must
    be evaluated before any new-entry candidate, every day."""
    cands = [_c("AGNC", "seed"), _c("ZZZT", "position"), _c("F", "seed")]
    for d in range(5):
        assert _ordered(cands, ordinal=d)[0].ticker == "ZZZT"


def test_empty_and_positions_only_are_safe():
    assert _ordered([], ordinal=3) == []
    only = [_c("A", "position")]
    assert [c.ticker for c in _ordered(only, ordinal=9)] == ["A"]


# --- the regime line parser ----------------------------------------------

def test_parse_regime_reads_the_writers_own_format():
    line = ("[pre_open] regime=risk_off as_of=2026-08-25T12:30:00Z "
            ":: futures red, VIX 22")
    regime, as_of = parse_market_regime(line)
    assert regime == "risk_off"
    assert as_of == "2026-08-25T12:30:00Z"


def test_parse_regime_rejects_garbage_quietly():
    assert parse_market_regime("") == (None, None)
    assert parse_market_regime(None) == (None, None)
    regime, _ = parse_market_regime("[x] regime=bananas as_of=t :: ?")
    assert regime is None, "an unvalidated regime token leaked through"
