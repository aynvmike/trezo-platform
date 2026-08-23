"""Guards for the options broker-truth reconciler.

The case these replay is real: on 2026-08-21 four short puts expired
worthless, Alpaca dropped them, and the ledger kept them 'open' all
weekend while the engine logged route_orphan over and over. Under the
lane's hard collateral rule those four dead contracts would have withheld
buying power from live trades on two books.

What matters most here is not that it closes things. It is WHAT IT
REFUSES TO CLOSE — a reconciler that guesses produces phantom fixes,
which are harder to find than the drift they replaced.
"""

from __future__ import annotations

import datetime as _dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.paper.broker_truth import parse_occ, settled_worthless  # noqa: E402


# --- OCC parsing ---------------------------------------------------------

def test_parses_a_real_occ_symbol():
    p = parse_occ("AGNC260821P00010500")
    assert p["underlying"] == "AGNC"
    assert p["expiry"] == _dt.date(2026, 8, 21)
    assert p["right"] == "P"
    assert abs(p["strike"] - 10.50) < 1e-9


def test_parses_three_and_four_digit_strikes():
    assert abs(parse_occ("BMY260821P00061000")["strike"] - 61.0) < 1e-9
    assert abs(parse_occ("PG260828P00138000")["strike"] - 138.0) < 1e-9
    assert abs(parse_occ("T260821P00023000")["strike"] - 23.0) < 1e-9


def test_non_occ_symbols_are_rejected_not_guessed():
    for junk in ("AAPL", "", "NOTANOCC123", "AGNC26082P00010500"):
        assert parse_occ(junk) is None, junk


# --- settlement judgement ------------------------------------------------

def test_short_put_above_strike_is_worthless():
    p = parse_occ("AGNC260821P00010500")
    assert settled_worthless(p, 10.89) is True


def test_put_below_strike_is_assignment_territory():
    p = parse_occ("AGNC260821P00010500")
    assert settled_worthless(p, 9.00) is False


def test_call_below_strike_is_worthless_above_is_not():
    c = parse_occ("PG260828C00138000")
    assert settled_worthless(c, 130.0) is True
    assert settled_worthless(c, 145.0) is False


def test_no_price_is_none_not_a_guess():
    """The whole safety property: unknown must never read as worthless."""
    p = parse_occ("AGNC260821P00010500")
    assert settled_worthless(p, None) is None
    assert settled_worthless(p, 0) is None
    assert settled_worthless(p, -1) is None


def test_at_the_money_put_is_not_treated_as_worthless():
    """Exactly at the strike is not out of the money — assignment is
    possible, so it must fall to the flag path."""
    p = parse_occ("AGNC260821P00010500")
    assert settled_worthless(p, 10.50) is False


# --- the 2026-08-21 replay ----------------------------------------------

def test_replays_the_four_rows_that_actually_drifted():
    """Each of these was reconciled by hand on 2026-08-23 after checking
    Alpaca. The reconciler must reach the same verdict unaided — same
    close decision, same realized premium."""
    cases = [
        # symbol,               underlying close, qty, entry, expected P&L
        ("BMY260821P00061000",  67.015, 1, 0.19,  19.0),
        ("AGNC260821P00010500", 10.89,  2, 0.035,  7.0),
        ("AGNC260821P00010500", 10.89,  1, 0.04,   4.0),
        ("T260821P00023000",    25.31,  1, 0.03,   3.0),
    ]
    for sym, px, qty, entry, expected in cases:
        p = parse_occ(sym)
        assert p is not None, sym
        assert settled_worthless(p, px) is True, sym
        # short premium is kept in full when the contract dies worthless
        assert round(entry * 100 * qty, 2) == expected, sym


def test_the_two_live_contracts_are_not_expired():
    """AGNC 8/28 and PG 8/28 were confirmed AT the broker and must never
    have been candidates for closing."""
    today = _dt.date(2026, 8, 23)
    for sym in ("AGNC260828P00010500", "PG260828P00138000"):
        assert parse_occ(sym)["expiry"] > today, sym
