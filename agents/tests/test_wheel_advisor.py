"""Guards for the Wheel Advisor gate.

The most important tests in this file are the ones that prove the gate
CANNOT break the Wheel. It was added to a 2,753-line agent that already
worked; the whole design bet is that an advisory layer is safe precisely
because every failure mode allows. If `test_broken_advisor_fails_open`
ever fails, the bet is off.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.strategies.wheel_advisor import (  # noqa: E402
    ENV_FLAG, MAX_DTE, MIN_DTE, advise_wheel_leg, advisor_enabled,
    check_collateral, check_ex_date, check_schedule, check_tier,
)


def _days_out(n: int) -> str:
    return (_dt.datetime.now(_dt.timezone.utc).date()
            + _dt.timedelta(days=n)).isoformat()


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# --- the safety property -------------------------------------------------

def test_broken_advisor_fails_open():
    """If anything inside throws, the leg is ALLOWED. This is the whole
    reason an advisory gate is safe to bolt onto a working lane."""
    v = _run(advise_wheel_leg(
        user_id="u", underlying="O", strategy="wheel_csp",
        strike=float("nan"), expiration="not-a-date", contracts=1))
    assert v.allow is True, v.reason


def test_env_flag_disables_the_whole_gate():
    os.environ[ENV_FLAG] = "0"
    try:
        assert advisor_enabled() is False
        v = _run(advise_wheel_leg(
            user_id="u", underlying="JNJ", strategy="wheel_cc",
            strike=100.0, expiration=_days_out(20), tier="GROWTH"))
        # GROWTH + covered call would normally defer; disabled means allow.
        assert v.allow is True
        assert "disabled" in v.reason
    finally:
        os.environ.pop(ENV_FLAG, None)


def test_advisor_defaults_on():
    os.environ.pop(ENV_FLAG, None)
    assert advisor_enabled() is True


def test_verdict_never_raises_contract_count():
    v = _run(advise_wheel_leg(
        user_id="u", underlying="O", strategy="wheel_csp",
        strike=50.0, expiration=_days_out(20), contracts=3))
    assert v.max_contracts is None or v.max_contracts <= 3


# --- schedule ------------------------------------------------------------

def test_too_near_expiration_defers():
    v = check_schedule(_days_out(MIN_DTE - 2))
    assert v.allow is False and v.rule == "schedule.dte_floor"
    assert v.clears_when


def test_too_far_expiration_defers():
    v = check_schedule(_days_out(MAX_DTE + 10))
    assert v.allow is False and v.rule == "schedule.dte_ceiling"


def test_expiration_inside_the_window_allows():
    assert check_schedule(_days_out(30)).allow is True


def test_earnings_in_two_days_defers():
    v = check_schedule(_days_out(30), next_earnings=_days_out(1))
    assert v.allow is False and v.rule == "schedule.earnings_blackout"


def test_earnings_spanning_the_leg_allows_but_notes_it():
    v = check_schedule(_days_out(30), next_earnings=_days_out(10))
    assert v.allow is True
    assert v.notes, "a leg spanning earnings should say so"


def test_unparseable_expiration_allows():
    assert check_schedule("garbage").allow is True


# --- tier (lane rule 4) --------------------------------------------------

def test_growth_tier_cannot_wear_a_call():
    v = check_tier("wheel_cc", "GROWTH")
    assert v.allow is False and v.rule == "lane_rule_4.growth_no_calls"


def test_growth_tier_can_still_be_acquired_by_csp():
    """Selling a put to ACQUIRE a compounder at a discount is fine — it
    is capping its upside with a call that the rule forbids."""
    assert check_tier("wheel_csp", "GROWTH").allow is True


def test_high_yield_may_wear_a_call():
    assert check_tier("wheel_cc", "HIGH_YIELD").allow is True


def test_unknown_tier_allows_rather_than_blocking_on_silence():
    """The screen ratchets over time; a name it hasn't reached must not
    be gated by that absence."""
    assert check_tier("wheel_cc", None).allow is True
    assert check_tier("wheel_cc", "UNKNOWN").allow is True


# --- ex-date (lane rule 3) ----------------------------------------------

def test_itm_call_into_ex_date_defers():
    v = check_ex_date(strategy="wheel_cc", strike=50.0, spot=55.0,
                      expiration="2099-12-31", ex_date="2099-06-01")
    assert v.allow is False and v.rule == "lane_rule_3.ex_date_guard"


def test_expiration_clearing_ex_date_allows():
    v = check_ex_date(strategy="wheel_cc", strike=50.0, spot=55.0,
                      expiration="2099-05-01", ex_date="2099-06-01")
    assert v.allow is True


def test_csp_is_never_gated_on_ex_date():
    """A short put cannot lose a dividend to early exercise."""
    v = check_ex_date(strategy="wheel_csp", strike=50.0, spot=55.0,
                      expiration="2099-12-31", ex_date="2099-06-01")
    assert v.allow is True


# --- collateral (lane rule 5) -------------------------------------------

def test_csp_beyond_free_lane_cash_defers():
    v = check_collateral(strategy="wheel_csp", strike=35.0, contracts=1,
                         lane_cash=5_000, reserved_for_open_csps=3_500)
    assert v.allow is False and v.rule == "lane_rule_5.collateral"


def test_csp_within_free_lane_cash_allows():
    v = check_collateral(strategy="wheel_csp", strike=35.0, contracts=1,
                         lane_cash=10_000, reserved_for_open_csps=3_500)
    assert v.allow is True


def test_unknown_ledger_cash_allows_rather_than_guessing():
    v = check_collateral(strategy="wheel_csp", strike=35.0, contracts=1,
                         lane_cash=None, reserved_for_open_csps=None)
    assert v.allow is True


def test_covered_call_is_not_collateral_gated():
    v = check_collateral(strategy="wheel_cc", strike=35.0, contracts=1,
                         lane_cash=0, reserved_for_open_csps=0)
    assert v.allow is True


# --- shrink (design rule 2: "defer or SHRINK it") ------------------------

def test_partial_fit_shrinks_instead_of_deferring():
    """3 contracts need $10,500; only $6,500 is free — but ONE fits.
    The audit found max_contracts documented and never set; this is the
    branch that sets it."""
    v = check_collateral(strategy="wheel_csp", strike=35.0, contracts=3,
                         lane_cash=10_000, reserved_for_open_csps=3_500)
    assert v.allow is True
    assert v.max_contracts == 1
    assert v.rule == "lane_rule_5.collateral_shrink"


def test_zero_fit_still_defers_not_shrinks():
    """$1,500 free cannot back even one $3,500 contract — a shrink to
    zero is a defer, and must say so."""
    v = check_collateral(strategy="wheel_csp", strike=35.0, contracts=2,
                         lane_cash=5_000, reserved_for_open_csps=3_500)
    assert v.allow is False
    assert v.max_contracts is None


def test_inconsistent_ledger_never_shrinks():
    """More reserved than exists is a bookkeeping fault; sizing a trade
    from it would launder the inconsistency into an order."""
    v = check_collateral(strategy="wheel_csp", strike=35.0, contracts=2,
                         lane_cash=3_000, reserved_for_open_csps=5_000)
    assert v.allow is False
    assert v.max_contracts is None


def test_shrink_propagates_through_the_gate():
    """The end-to-end promise: the final verdict from advise_wheel_leg
    carries the check's max_contracts instead of rebuilding a bare
    allow (the exact drop the audit flagged)."""
    v = _run(advise_wheel_leg(
        user_id="u", underlying="O", strategy="wheel_csp",
        strike=35.0, expiration=_days_out(20), contracts=3,
        lane_cash=10_000, reserved_for_open_csps=3_500))
    assert v.allow is True
    assert v.max_contracts == 1
    assert v.rule == "advisor.shrink"


def test_full_fit_sets_no_shrink():
    v = _run(advise_wheel_leg(
        user_id="u", underlying="O", strategy="wheel_csp",
        strike=35.0, expiration=_days_out(20), contracts=1,
        lane_cash=10_000, reserved_for_open_csps=3_500))
    assert v.allow is True
    assert v.max_contracts is None


# --- payload shape -------------------------------------------------------

def test_block_payload_matches_the_scanners_existing_shape():
    """options_scanner already emits wheel_auto_blocked; the advisor must
    speak that same dialect so nothing downstream learns a new format."""
    v = check_tier("wheel_cc", "GROWTH")
    p = v.as_block_payload("JNJ", "wheel_cc")
    assert p["event"] == "wheel_auto_blocked"
    assert p["underlying"] == "JNJ" and p["strategy"] == "wheel_cc"
    assert p["advisor"] is True
    assert p["reason"].startswith("[advisor/")
