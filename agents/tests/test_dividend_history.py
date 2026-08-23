"""Guards for the dividend PAYMENT SERIES — the layer every other rule reads.

Three separate ways the raw feed lies, each of which manufactured a
dividend cut at a company that never cut one:

  1. SPLITS. Alpaca reports each dividend at the rate declared at the
     time. NextEra split 4-for-1 in 2020, so its series read 5.00 ->
     1.54 and a two-decade raiser came back as a 66% cut. Nine of 120
     names in the scan universe were misread this way.
  2. SPECIALS. The `special` flag is set on almost nothing -- 9 rows in
     that same 120-name universe. Costco's unflagged $7.00 in 2017 made
     2018 look like a 75% cut.
  3. INCOMPLETE YEARS. Alpaca's history for a name can begin mid-series.
     Accenture's early years hold two of four payments; the old +/-2
     tolerance scaled them up by 2x on the strength of missing data.

The tests below are written against synthetic series so they state the
RULE rather than today's market data, which moves.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.data.corporate_actions import (  # noqa: E402
    CUT_HEAL_YEARS, _apply_split_adjustment, _complete_years, cut_profile,
    had_cut, raise_streak_years,
)


def _div(date: str, rate: float, special: bool = False) -> dict:
    return {"ex_date": date, "rate": rate, "special": special}


def _quarterly(year: int, rate: float) -> list:
    return [_div(f"{year}-{m:02d}-15", rate) for m in (2, 5, 8, 11)]


def _series(per_year: dict) -> list:
    out: list = []
    for y, rate in sorted(per_year.items()):
        out += _quarterly(y, rate)
    return out


# --- 1. splits -----------------------------------------------------------

def test_a_forward_split_is_not_a_dividend_cut():
    """The NextEra case. Same real dividend, four times the shares."""
    rows = _series({2019: 1.25, 2020: 1.30}) + _quarterly(2021, 0.35)
    split = [{"ex_date": "2020-12-01", "old_rate": 1, "new_rate": 4}]
    _apply_split_adjustment(rows, split)
    # 1.25 declared before the split is 0.3125 in today's shares.
    assert abs(rows[0]["adj_rate"] - 0.3125) < 1e-9
    # ...and the post-split payment is untouched.
    assert abs(rows[-1]["adj_rate"] - 0.35) < 1e-9
    assert had_cut(rows) is False, "a split must not read as a cut"


def test_a_reverse_split_scales_the_other_way():
    """TSLY, 5:1. A payment made before it was worth five times as much
    per share as the raw number suggests."""
    rows = [_div("2025-06-01", 1.00)]
    _apply_split_adjustment(rows, [{"ex_date": "2025-12-01",
                                    "old_rate": 5, "new_rate": 1}])
    assert abs(rows[0]["adj_rate"] - 5.0) < 1e-9


def test_no_splits_leaves_every_rate_alone():
    rows = _series({2023: 1.0, 2024: 1.1})
    _apply_split_adjustment(rows, [])
    assert all(abs(r["adj_rate"] - r["rate"]) < 1e-12 for r in rows)


# --- 2. specials ---------------------------------------------------------

def test_an_unflagged_special_is_stripped():
    """Costco: four ~0.45 payments plus an unflagged 7.00 in 2017. Left
    in, the following year reads as a 75% cut."""
    rows = _series({2017: 0.45, 2018: 0.50})
    rows.append(_div("2017-05-08", 7.00))       # special=False on purpose
    rows.sort(key=lambda r: r["ex_date"])
    _apply_split_adjustment(rows, [])
    by = _complete_years(rows)
    assert by[2017] < 2.5, f"the special leaked into the year: {by[2017]}"
    assert had_cut(rows) is False


def test_a_reinstatement_is_not_a_special():
    """GE pays 0.28 four times after years at 0.02. Every payment in the
    year moves together, so none of them is an outlier -- measuring
    against the WINDOW median would have stripped all four."""
    rows = _series({2022: 0.02, 2023: 0.02, 2024: 0.28})
    _apply_split_adjustment(rows, [])
    by = _complete_years(rows)
    assert abs(by[2024] - 4 * 0.28) < 1e-9, "the reinstatement was eaten"


def test_a_stray_fragment_does_not_corrupt_the_payment_count():
    """Allstate's 2023 record: four 0.89 dividends and a stray 0.08.
    Counted as five payments against a norm of four, the year was scaled
    by 4/5 and a company that has never cut came back as a 14% cut."""
    rows = _series({2022: 0.85, 2023: 0.89, 2024: 0.92})
    rows.append(_div("2023-03-30", 0.08))
    rows.sort(key=lambda r: r["ex_date"])
    _apply_split_adjustment(rows, [])
    by = _complete_years(rows)
    assert abs(by[2023] - 3.56) < 1e-9, f"fragment corrupted the year: {by[2023]}"
    assert had_cut(rows) is False


def test_fragments_can_reveal_a_year_is_incomplete():
    """Ares Capital's 2019: two real 0.40 payments and two 0.02 stubs.
    Counting the stubs makes it look like a full year at half the cash.
    Discounting them, the year is visibly short and gets dropped."""
    rows = _series({2018: 0.40, 2020: 0.40, 2021: 0.41, 2022: 0.42})
    rows += [_div("2019-03-14", 0.40), _div("2019-06-13", 0.02),
             _div("2019-09-13", 0.40), _div("2019-12-13", 0.02)]
    rows.sort(key=lambda r: r["ex_date"])
    _apply_split_adjustment(rows, [])
    assert 2019 not in _complete_years(rows)
    assert had_cut(rows) is False, "half a year read as a cut"


def test_a_frequency_change_is_not_a_special():
    """STAG went monthly -> quarterly: bigger payments, same annual cash."""
    rows = [_div(f"2024-{m:02d}-28", 0.125) for m in range(1, 13)]
    rows += [_div(f"2025-{m:02d}-28", 0.375) for m in (3, 6, 9, 12)]
    _apply_split_adjustment(rows, [])
    # Every 2025 payment is 3x every 2024 payment, but they moved
    # TOGETHER, so none is an outlier inside its own year.
    assert all(r.get("adj_rate") == r["rate"] for r in rows)
    # The year is dropped rather than compared on an incompatible payment
    # count -- a known limitation, and the honest one: what must never
    # happen is a phantom CUT, and that is what is asserted here.
    assert had_cut(rows) is not True


# --- 3. incomplete years -------------------------------------------------

def test_a_month_slipping_across_new_year_is_corrected():
    """Realty Income: 11 payments one year, 13 the next, nothing about
    the dividend changed. This is the case the tolerance exists for."""
    rows = [_div(f"{y}-{m:02d}-01", 0.25)
            for y in (2022, 2023) for m in range(1, 13)]
    rows += [_div(f"2024-{m:02d}-01", 0.26) for m in range(1, 12)]   # 11
    rows += [_div(f"2025-{m:02d}-01", 0.27) for m in range(1, 13)]
    rows += [_div("2025-12-20", 0.27)]                               # 13
    rows.sort(key=lambda r: r["ex_date"])
    _apply_split_adjustment(rows, [])
    assert had_cut(rows) is False, "a calendar shift read as a cut"


def test_a_half_recorded_year_is_dropped_not_scaled():
    """Accenture: two of four payments in the early years. Scaling that
    up by 2x asserts a number the data does not contain."""
    rows = [_div(f"{y}-{m:02d}-15", 1.10) for y in (2016, 2017)
            for m in (5, 11)]                       # 2 payments/yr
    rows += _series({2018: 1.00, 2019: 1.05, 2020: 1.10, 2021: 1.15})
    rows.sort(key=lambda r: r["ex_date"])
    _apply_split_adjustment(rows, [])
    by = _complete_years(rows)
    assert 2016 not in by and 2017 not in by, "half-years must be dropped"
    assert had_cut(rows) is False


def test_extra_payments_are_kept_as_real_cash():
    """A supplemental is not a timing artifact; it was paid."""
    rows = _series({2023: 1.00, 2024: 1.00})
    rows += [_div("2024-06-30", 0.40), _div("2024-09-30", 0.40)]
    rows.sort(key=lambda r: r["ex_date"])
    _apply_split_adjustment(rows, [])
    by = _complete_years(rows)
    assert by[2024] > by[2023], "supplementals were discarded"


# --- 4. the repaired cut -------------------------------------------------

def _cut_then(recovery: dict) -> list:
    """Peak 4.00, cut to 2.00, then whatever `recovery` says."""
    rows = _series({2017: 0.90, 2018: 0.95, 2019: 1.00, 2020: 0.50})
    rows += _series(recovery)
    rows.sort(key=lambda r: r["ex_date"])
    _apply_split_adjustment(rows, [])
    return rows


def test_a_cut_that_climbed_back_above_its_peak_is_repaired():
    """Simon Property. Back above the pre-cut level, raising every year
    since the trough, and old enough to be a policy."""
    c = cut_profile(_cut_then({2021: 0.60, 2022: 0.80, 2023: 0.95,
                               2024: 1.02, 2025: 1.08}))
    assert c["had_cut"] is True
    assert c["recovered"] is True
    assert c["repaired"] is True


def test_a_cut_still_paying_less_than_before_is_not_repaired():
    """AT&T. Rising again, but from far below where it was."""
    c = cut_profile(_cut_then({2021: 0.55, 2022: 0.60, 2023: 0.65,
                               2024: 0.70, 2025: 0.75}))
    assert c["recovered"] is False
    assert c["repaired"] is False


def test_a_recovered_but_flat_payout_is_not_repaired():
    """Ares Capital. It stopped falling; it did not start raising."""
    c = cut_profile(_cut_then({2021: 1.05, 2022: 1.05, 2023: 1.05,
                               2024: 1.05, 2025: 1.05}))
    assert c["recovered"] is True
    assert c["repaired"] is False, "flat is not a recovery"


def test_a_fresh_rebound_has_not_healed_yet():
    """One good year after a cut is a bounce, not a policy."""
    c = cut_profile(_cut_then({2021: 1.10}))
    assert c["years_since_trough"] < CUT_HEAL_YEARS
    assert c["repaired"] is False


def test_a_clean_record_reports_no_cut_and_no_repair():
    c = cut_profile(_series({2021: 1.0, 2022: 1.1, 2023: 1.2,
                             2024: 1.3, 2025: 1.4}))
    assert c["had_cut"] is False
    assert c["repaired"] is False


def test_repair_never_invents_a_streak():
    """Whatever the repair rule concludes, the streak is still counted
    from the payments -- it is not a second lever on the same verdict."""
    rows = _cut_then({2021: 0.60, 2022: 0.80, 2023: 0.95,
                      2024: 1.02, 2025: 1.08})
    assert raise_streak_years(rows) == 5
