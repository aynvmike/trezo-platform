"""Guard tests: strategy-switching friction, on the scale TCS actually uses.

TCS became a single 0-100 scale on 2026-07-08. The adaptive branch was
migrated then. The tiered branch was NOT -- it kept testing `>= 700` and
`>= 500` against scores that top out at 100, so every score fell past
both bands to the final return and tiered silently meant "a flat 20%,
always". Three bands collapsed into one, for six weeks, while the
settings page went on describing all three.

Mike found it on 2026-08-19 by reading the UI and asking whether it
would confuse the agents. It had confused him first, which is usually
the order.

The lesson these encode: a half-finished migration is worse than an
unstarted one, because the migrated half proves the work "was done".

Run: python -m agents.tests.test_switch_friction   (or pytest)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _bootstrap import load_module, run_tests, stub_config  # noqa: E402

stub_config()
settings = load_module("app.runtime.settings")
req = settings.required_switch_advantage


def test_every_tiered_band_is_reachable():
    """The bug, stated as a property. On a 0-100 scale a threshold of
    700 can never be met, so a band keyed on it is dead code that looks
    alive."""
    bands = {req("tiered", 10, 70, tcs) for tcs in range(0, 101)}
    assert bands == {0.05, 0.10, 0.20}, (
        f"tiered collapsed to {bands} -- a band no score can reach is a "
        f"setting that lies to the person who picked it")


def test_the_tiered_boundaries_are_where_the_ui_says():
    assert req("tiered", 10, 70, 70) == 0.05
    assert req("tiered", 10, 70, 69) == 0.10
    assert req("tiered", 10, 70, 50) == 0.10
    assert req("tiered", 10, 70, 49) == 0.20


def test_tiered_ignores_base_pct():
    assert req("tiered", 99, 70, 80) == req("tiered", 1, 70, 80)


def test_adaptive_demands_a_bigger_gap_at_a_noisier_threshold():
    """Lower TCS floor = noisier signals = a challenger must beat the
    incumbent by more before the engine flips."""
    assert req("adaptive", 10, 50, 90) > req("adaptive", 10, 80, 90)
    assert abs(req("adaptive", 10, 50, 90) - 0.16) < 1e-9
    assert abs(req("adaptive", 10, 80, 90) - 0.10) < 1e-9


def test_adaptive_friction_never_gets_easier_than_the_base():
    """Anchored at 80: above it the multiplier would drop below 1.0 and
    quietly make flipping EASIER than the operator asked for."""
    for thr in (80, 90, 100):
        assert req("adaptive", 10, thr, 90) >= 0.10


def test_off_flips_on_any_improvement():
    assert req("off", 10, 70, 71) == 0.0


def test_fixed_is_exactly_the_dial():
    assert abs(req("fixed", 15, 70, 90) - 0.15) < 1e-9


def test_a_zero_threshold_does_not_divide_by_zero():
    assert req("adaptive", 10, 0, 90) == 0.10


def test_an_unknown_mode_falls_back_to_adaptive_not_to_nothing():
    """Failing open here would mean zero friction and a pick that flips
    every tick -- the whipsaw this control exists to prevent."""
    assert req("banana", 10, 50, 90) == req("adaptive", 10, 50, 90)


if __name__ == "__main__":
    sys.exit(run_tests(dict(globals())))
