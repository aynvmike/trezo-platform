"""Guards for the dividend-trend proxy — added after the 3-month replay.

The replay found two defects that no unit test would have caught, because
both only appear when the screen meets real API data:

  1. Finnhub's /stock/dividend payment series is not on this tier. The
     first version marked raise_streak and no_cut UNVERIFIED, so `passed`
     was never true and the screen admitted NOTHING. A gate that blocks
     everything is not strict, it is broken.
  2. The available substitute, dividendGrowthRate5Y, INVERTS the rule it
     proxies: a company that cut to zero and restarted shows a huge 5Y
     CAGR off a near-zero base. TMUS printed 123.7% and Ford 38.1%, and
     the ranking put both at the TOP of the ladder -- precisely the names
     "no cut in 10 years" exists to exclude.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.strategies.dividend_screen import (  # noqa: E402
    MAX_PLAUSIBLE_GROWTH, MIN_TTM_VS_ANNUAL, ScreenResult,
)


def test_the_decisive_set_excludes_unavailable_data():
    """The whole bug in one assertion: eligibility must not depend on a
    check we have no source for, or the lane starves."""
    import inspect
    from app.strategies import dividend_screen
    src = inspect.getsource(dividend_screen.screen)
    assert 'decisive = ("yield", "payout_ratio", "dividend_trend")' in src, (
        "decisive set must be the checks this data tier can answer")
    assert '"raise_streak"' not in src.split("decisive =")[1][:200]


def test_reinstatement_threshold_is_sane():
    """25%/yr sustained for five years is not a raise streak."""
    assert 0.15 <= MAX_PLAUSIBLE_GROWTH <= 0.40


def test_shrink_threshold_is_sane():
    assert 0.80 <= MIN_TTM_VS_ANNUAL < 1.0


def test_result_carries_the_growth_proxy():
    r = ScreenResult(ticker="X", dividend_growth_5y=0.077)
    assert r.dividend_growth_5y == 0.077


def test_unverified_still_blocks_eligibility():
    """ETFs come back unverified on this tier — they must not slip
    through as eligible just because the trend check was skipped."""
    r = ScreenResult(ticker="SCHD", passed=False, tier="UNVERIFIED")
    assert r.wheel_eligible is False and r.ladder_eligible is False


def test_growth_and_shrink_boundaries_classify_correctly():
    """The exact cases from the replay, as pure arithmetic."""
    cases = [
        ("TMUS", 1.237, "artifact"),   # initiation off ~zero
        ("F",    0.381, "artifact"),   # reinstated after a cut
        ("MAIN", 0.117, "ok"),
        ("JNJ",  0.077, "ok"),
        ("NLY", -0.068, "shrinking"),
        ("T",   -0.112, "shrinking"),
    ]
    for sym, g, expect in cases:
        if g > MAX_PLAUSIBLE_GROWTH:
            got = "artifact"
        elif g < 0:
            got = "shrinking"
        else:
            got = "ok"
        assert got == expect, f"{sym}: {g} classified {got}, expected {expect}"


def test_ford_is_caught_by_the_shrink_rule_too():
    """Belt and braces: Ford's TTM dividend sat below its annual rate, so
    even if the growth artifact rule missed it, 'shrinking now' catches
    it independently."""
    dps_annual, dps_ttm = 0.73, 0.57
    assert dps_ttm < dps_annual * MIN_TTM_VS_ANNUAL
