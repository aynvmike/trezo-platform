"""Guards for the Dividends (Long-Term) lane.

Runs under the repo's plain-stdlib test runner (no pytest dependency):
each `test_*` function asserts and raises on failure.

What these protect, in order of how much they'd cost to get wrong:
  - the collateral reservation (rule 5) — the accounting-collision bug
  - the ex-date guard (rule 3) — silently donating dividends
  - GROWTH tier never writing calls (rule 4) — selling the compounding
  - expected TR being FLAT across capital — "size buys mechanics, not
    edge" is the whole thesis; a regression here would be invisible
  - the target readout never actuating anything
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.strategies.dividend_lt import (  # noqa: E402
    ASSIGNED, CASH_SECURED, FRACTIONAL, LOT_HELD, LOT_READY,
    LaneGuardrailError, LaneInputs, can_write_covered_call, income_draw,
    name_state, per_name_cap_pct, project, size_lane, target_readout,
)
from app.strategies.dividend_lane_rules import (  # noqa: E402
    check_collateral, csp_collateral_required, ex_date_guard,
    two_state_check,
)
from app.strategies.dividend_screen import (  # noqa: E402
    ScreenResult, _cut_in_lookback, _raise_streak_from_series, sector_capped,
)


# --- §1 guardrails --------------------------------------------------------

def test_wheel_weight_above_cap_is_refused_not_clamped():
    """w_wheel > 40% is a different strategy, not an aggression setting."""
    try:
        LaneInputs(capital=50_000, w_ladder=0.50, w_wheel=0.45, w_buffer=0.05)
    except LaneGuardrailError as e:
        assert "w_wheel" in str(e)
        return
    raise AssertionError("w_wheel=0.45 should have been refused")


def test_wheel_delta_is_hard_capped():
    try:
        LaneInputs(capital=50_000, wheel_delta=0.55)
    except LaneGuardrailError:
        return
    raise AssertionError("wheel_delta=0.55 should have been refused")


def test_weights_normalize_to_one():
    i = LaneInputs(capital=10_000, w_ladder=0.70, w_wheel=0.25,
                   w_buffer=0.10).normalized()
    total = i.w_ladder + i.w_wheel + i.w_buffer
    assert abs(total - 1.0) < 1e-9, total


# --- §2 sizing ------------------------------------------------------------

def test_expected_tr_is_flat_across_capital():
    """Size buys mechanics, not edge. If this test ever fails, some code
    started implying bigger = better-returning, which the spec calls a
    bug in so many words."""
    trs = []
    for cap in (2_000, 20_000, 100_000, 250_000):
        trs.append(round(size_lane(LaneInputs(capital=cap)).expected_tr, 6))
    assert len(set(trs)) == 1, f"expected TR drifted with capital: {trs}"


def test_small_capital_gets_no_csp_blocks():
    s = size_lane(LaneInputs(capital=5_000))
    assert s.csp_blocks == 0, s.csp_blocks
    assert s.unlocks["U1_wheel"] is False


def test_ladder_names_cap_at_fifteen():
    s = size_lane(LaneInputs(capital=1_000_000))
    assert s.ladder_names == 15, s.ladder_names


def test_unlocks_fire_at_the_documented_levels():
    s = size_lane(LaneInputs(capital=50_000))
    assert s.unlocks["U4_selectivity"] is True
    assert size_lane(LaneInputs(capital=49_000)).unlocks["U4_selectivity"] is False


def test_concentration_cap_binds_until_twelve_names():
    thin = size_lane(LaneInputs(capital=10_000))
    wide = size_lane(LaneInputs(capital=100_000))
    assert per_name_cap_pct(thin) == 0.20
    assert per_name_cap_pct(wide) == 0.10


# --- §3 states + rule 4 ---------------------------------------------------

def test_growth_tier_never_writes_calls_even_with_a_round_lot():
    """The capture-asymmetry mistake, prevented structurally."""
    state = name_state(500, "GROWTH")
    assert state == LOT_HELD, state
    ok, reason = can_write_covered_call(state, "GROWTH")
    assert ok is False
    assert "GROWTH" in reason


def test_high_yield_round_lot_is_call_eligible():
    state = name_state(100, "HIGH_YIELD")
    assert state == LOT_READY, state
    ok, _ = can_write_covered_call(state, "HIGH_YIELD")
    assert ok is True


def test_fractional_is_dividend_only():
    state = name_state(99, "HIGH_YIELD")
    assert state == FRACTIONAL, state
    ok, reason = can_write_covered_call(state, "HIGH_YIELD")
    assert ok is False and "100 shares" in reason


def test_unverified_tier_cannot_write_calls():
    ok, _ = can_write_covered_call(LOT_READY, "UNVERIFIED")
    assert ok is False


def test_cash_secured_and_assigned_states():
    assert name_state(0, "HIGH_YIELD", cash_reserved_for_csp=True) == CASH_SECURED
    assert name_state(100, "HIGH_YIELD",
                      came_from_assignment=True) == ASSIGNED


# --- rule 3: ex-date guard ------------------------------------------------

def test_itm_call_into_ex_date_is_blocked():
    v = ex_date_guard(strike=50.0, spot=55.0, expiration="2099-12-31",
                      ex_date="2099-06-01")
    assert v.allowed is False
    assert "ex-date" in v.reason


def test_expiration_before_ex_date_is_allowed():
    v = ex_date_guard(strike=50.0, spot=55.0, expiration="2099-05-01",
                      ex_date="2099-06-01")
    assert v.allowed is True
    assert "clears" in v.reason


def test_itm_with_fat_time_value_is_allowed():
    """Early exercise is irrational when time value exceeds the dividend."""
    v = ex_date_guard(strike=50.0, spot=55.0, expiration="2099-12-31",
                      ex_date="2099-06-01",
                      remaining_time_value=2.00, dividend_amount=0.55)
    assert v.allowed is True


def test_itm_with_thin_time_value_is_blocked():
    v = ex_date_guard(strike=50.0, spot=55.0, expiration="2099-12-31",
                      ex_date="2099-06-01",
                      remaining_time_value=0.10, dividend_amount=0.55)
    assert v.allowed is False


def test_razor_thin_otm_buffer_is_blocked():
    v = ex_date_guard(strike=50.2, spot=50.0, expiration="2099-12-31",
                      ex_date="2099-06-01")
    assert v.allowed is False, v.reason


# --- rule 5: collateral ---------------------------------------------------

def test_collateral_is_strike_times_one_hundred():
    assert csp_collateral_required(35.0, 1) == 3500.0
    assert csp_collateral_required(35.0, 3) == 10500.0


def test_collateral_cannot_double_count_open_csps():
    """The accounting-collision bug this rule exists to prevent."""
    c = check_collateral(strike=35.0, contracts=1, lane_cash=5_000,
                         reserved_for_open_csps=3_500)
    assert c.ok is False, c.reason
    assert c.available == 1_500


def test_collateral_passes_when_genuinely_free():
    c = check_collateral(strike=35.0, contracts=1, lane_cash=10_000,
                         reserved_for_open_csps=3_500)
    assert c.ok is True, c.reason


def test_inconsistent_ledger_refuses_rather_than_guessing():
    c = check_collateral(strike=35.0, contracts=1, lane_cash=1_000,
                         reserved_for_open_csps=3_500)
    assert c.ok is False
    assert "inconsistent" in c.reason


# --- rule 1: two-state ----------------------------------------------------

def test_simultaneous_put_and_call_is_refused():
    ok, reason = two_state_check(ticker="O", has_open_csp=True,
                                 has_open_covered_call=True, shares=0)
    assert ok is False and "simultaneous" in reason


def test_csp_on_a_name_already_owned_is_refused():
    ok, _ = two_state_check(ticker="O", has_open_csp=True,
                            has_open_covered_call=False, shares=200)
    assert ok is False


# --- §5 readout -----------------------------------------------------------

def test_readout_never_changes_sizing():
    """The slider explains; it must not actuate."""
    inp = LaneInputs(capital=75_000)
    before = size_lane(inp)
    target_readout(inp, before, target_return=0.20)
    after = size_lane(inp)
    assert before == after


def test_high_target_is_named_unreachable_with_its_blocking_rule():
    inp = LaneInputs(capital=75_000)
    r = target_readout(inp, size_lane(inp), target_return=0.20)
    assert r.reachable is False
    assert r.blocking_rule and "wheel_delta" in r.blocking_rule
    assert "unreachable" in r.note or "unreachable" in r.blocking_rule


def test_modest_target_is_reachable_and_names_both_paths():
    inp = LaneInputs(capital=75_000)
    r = target_readout(inp, size_lane(inp), target_return=0.10)
    assert r.reachable is True
    assert r.appreciation_required is not None
    assert r.premium_required is not None


def test_target_outside_slider_range_is_refused():
    inp = LaneInputs(capital=75_000)
    try:
        target_readout(inp, size_lane(inp), target_return=0.40)
    except LaneGuardrailError:
        return
    raise AssertionError("target_return=0.40 should have been refused")


# --- §6 projection + income ----------------------------------------------

def test_contributions_can_dwarf_growth():
    """The finding, not a footnote."""
    p = project(LaneInputs(capital=20_000, contribution_monthly=300), years=5)
    assert p["total_contributed"] == 18_000
    assert p["ending_balance"] > 45_000


def test_income_draw_never_exceeds_ninety_percent_of_total_return():
    assert income_draw(LaneInputs(capital=75_000), 5_000, 4_000) == 3_600
    assert income_draw(LaneInputs(capital=75_000), 1_000, 4_000) == 1_000
    assert income_draw(LaneInputs(capital=75_000), 5_000, -2_000) == 0.0


# --- screen ---------------------------------------------------------------

def test_raise_streak_counts_consecutive_years():
    series = [
        {"payDate": "2020-03-01", "amount": 1.00},
        {"payDate": "2021-03-01", "amount": 1.10},
        {"payDate": "2022-03-01", "amount": 1.20},
        {"payDate": "2023-03-01", "amount": 1.30},
    ]
    assert _raise_streak_from_series(series) == 3


def test_flat_year_ends_the_streak():
    series = [
        {"payDate": "2021-03-01", "amount": 1.10},
        {"payDate": "2022-03-01", "amount": 1.10},
        {"payDate": "2023-03-01", "amount": 1.30},
    ]
    assert _raise_streak_from_series(series) == 1


def test_cut_is_detected():
    series = [
        {"payDate": "2021-03-01", "amount": 2.00},
        {"payDate": "2022-03-01", "amount": 1.00},
        {"payDate": "2023-03-01", "amount": 1.10},
    ]
    assert _cut_in_lookback(series) is True


def test_no_history_is_unverified_not_false():
    """Silence is not consent — this is the honesty rule."""
    assert _cut_in_lookback([]) is None
    assert _raise_streak_from_series([]) is None


def test_unverified_screen_result_is_not_eligible():
    r = ScreenResult(ticker="XYZ", passed=False, tier="UNVERIFIED")
    assert r.wheel_eligible is False
    assert r.ladder_eligible is False


def test_growth_tier_is_ladder_but_not_wheel_eligible():
    r = ScreenResult(ticker="JNJ", passed=True, tier="GROWTH")
    assert r.ladder_eligible is True
    assert r.wheel_eligible is False


def test_sector_cap_drops_the_overflow():
    rows = [
        ScreenResult(ticker="A", passed=True, tier="GROWTH", sector="Banks"),
        ScreenResult(ticker="B", passed=True, tier="GROWTH", sector="Banks"),
        ScreenResult(ticker="C", passed=True, tier="GROWTH", sector="Banks"),
        ScreenResult(ticker="D", passed=True, tier="GROWTH", sector="Energy"),
    ]
    kept = [r.ticker for r in sector_capped(rows)]
    assert kept == ["A", "B", "D"], kept


def test_reit_and_bdc_share_one_sector_factor():
    rows = [
        ScreenResult(ticker="O", passed=True, tier="HIGH_YIELD",
                     sector="REIT"),
        ScreenResult(ticker="STAG", passed=True, tier="HIGH_YIELD",
                     sector="REIT—Diversified"),
        ScreenResult(ticker="MAIN", passed=True, tier="HIGH_YIELD",
                     sector="BDC"),
    ]
    kept = [r.ticker for r in sector_capped(rows)]
    assert len(kept) == 2, kept
