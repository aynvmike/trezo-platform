"""Guards for the R:R floor split that blocked every equity trade.

The case is real: the Risk Manager's harmonizer shaped each trade's
geometry to THIS BOOK's min_reward_risk (primary's Bot Tuning said 0.4,
so stop = target/0.4 exactly), while sizing enforced the GLOBAL row's
floor (0.5) -- so every equity approval died at execution, 6-for-6 on
8/31 and again at Monday's open: "Reward:risk 0.4 below your 0.5
floor". Measured per book, enforced global -- the platform's oldest
disease, sitting in the money path.

Two invariants pinned here:
  1. sizing reads the floor (and max_position_pct) for the BOOK it is
     sizing -- the same row the harmonizer read.
  2. enforcement tolerates one 2-dp rounding step: the harmonizer
     TARGETS the floor exactly, and cent-rounding of stop/target PRICES
     can shave the realized ratio a hair under it. A gate must not
     reject its own target.

Dependency-free (no pytest, no .env, no network) for the deploy gate.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _bootstrap import load_module, run_tests, stub_config  # noqa: E402

stub_config()

# sizing does `from app.runtime.settings import get_bot_settings` INSIDE
# the function, so it re-binds from sys.modules on every call. We load
# the REAL settings module and swap just that one attribute per test,
# ALWAYS restoring it -- run_all imports every suite into one process,
# and a fake module left in sys.modules breaks the suites that run
# after this one (found the hard way: test_switch_friction).
settings_mod = load_module("app.runtime.settings")
sizing = load_module("app.paper.sizing")

_SETTINGS = {"calls": [], "rows": {}}


class _Row:
    def __init__(self, floor):
        self.min_reward_risk = floor
        self.max_position_pct = None


def _fake_get_bot_settings(user_id=None):
    _SETTINGS["calls"].append(user_id)
    return _SETTINGS["rows"].get(user_id, _Row(1.5))


def _plan(entry=100.0, stop=98.5, target=100.6, uid="book-a", floor=0.4):
    """A harmonizer-shaped trade under a swapped-in settings read; the
    real get_bot_settings is always put back."""
    _SETTINGS["calls"].clear()
    _SETTINGS["rows"] = {uid: _Row(floor), None: _Row(1.5)}
    _real = settings_mod.get_bot_settings
    settings_mod.get_bot_settings = _fake_get_bot_settings
    try:
        return sizing.plan_position(
            equity=25_000.0, entry_price=entry, stop_price=stop,
            target_price=target, risk_pct=0.01, asset_type="stock",
            buying_power=25_000.0, user_id=uid)
    finally:
        settings_mod.get_bot_settings = _real


# --- invariant 1: the floor is THIS book's floor --------------------------

def test_sizing_asks_for_the_books_own_settings_row():
    _plan(uid="book-a", floor=0.4)
    assert "book-a" in _SETTINGS["calls"], (
        f"sizing never asked for book-a's settings: {_SETTINGS['calls']}")


def test_the_harmonizers_exact_target_passes_the_books_floor():
    """THE OUTAGE CASE: book floor 0.4, geometry shaped to exactly 0.4
    (stop 1.5%, target 0.6%). Under the old global read (floor 0.5)
    this rejected; under the book's own floor it must pass."""
    plan = _plan(entry=100.0, stop=98.5, target=100.6,
                 uid="book-a", floor=0.4)
    assert plan.ok, plan.reject_reason
    assert abs(plan.reward_risk - 0.4) < 0.02, plan.reward_risk


def test_a_book_with_a_strict_floor_still_rejects_thin_trades():
    """The floor is not weakened: a 1.5-floor book must still refuse
    the same 0.4 geometry."""
    plan = _plan(entry=100.0, stop=98.5, target=100.6,
                 uid="book-b", floor=1.5)
    assert not plan.ok
    assert "Reward:risk" in (plan.reject_reason or "")


def test_two_books_two_floors_two_verdicts_same_trade():
    """Book isolation, stated as one test: the identical trade passes
    the 0.4-floor book and fails the 1.5-floor book."""
    ok_plan = _plan(uid="loose", floor=0.4)
    no_plan = _plan(uid="tight", floor=1.5)
    assert ok_plan.ok and not no_plan.ok


# --- invariant 2: rounding tolerance --------------------------------------

def test_cent_rounding_cannot_reject_the_floors_own_target():
    """Prices rounded to cents can realize 0.39 against a 0.40 floor.
    One 2-dp step of grace, no more."""
    # entry 121.53, stop/target rounded to cents so ratio lands at 0.39
    plan = _plan(entry=121.53, stop=119.72, target=122.24,
                 uid="book-a", floor=0.4)
    # reward 0.71, risk 1.81 -> 0.39: inside the tolerance band
    assert plan.ok, plan.reject_reason


def test_the_tolerance_is_one_step_not_a_hole():
    """0.37 against a 0.40 floor is a genuinely thin trade, not
    rounding. It must still reject."""
    plan = _plan(entry=100.0, stop=98.0, target=100.74,
                 uid="book-a", floor=0.4)   # 0.74/2.00 = 0.37
    assert not plan.ok
    assert "Reward:risk" in (plan.reject_reason or "")


def test_the_typo_clamp_survives():
    """A floor typed as 0.0 (or 30) still clamps to [0.3, 3.0] -- a
    settings typo must not disable the gate entirely."""
    plan = _plan(entry=100.0, stop=98.0, target=100.2,
                 uid="book-a", floor=0.0)   # 0.2/2.0 = 0.1 vs clamped 0.3
    assert not plan.ok


def test_a_missing_settings_module_falls_back_to_the_seed():
    """Bare checkout: settings import fails -> seed floor 1.5 applies.
    The module is put back in sys.modules whatever happens."""
    saved = sys.modules.pop("app.runtime.settings", None)
    try:
        plan = sizing.plan_position(
            equity=25_000.0, entry_price=100.0, stop_price=98.5,
            target_price=100.6, risk_pct=0.01, asset_type="stock",
            buying_power=25_000.0, user_id="whoever")
        assert not plan.ok          # 0.4 vs seed 1.5
    finally:
        if saved is not None:
            sys.modules["app.runtime.settings"] = saved


if __name__ == "__main__":
    sys.exit(run_tests(dict(vars())))
