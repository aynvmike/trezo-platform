"""Per-book kill-switches + the weekly RECOVERY mode (Mike 2026-08-27).

The two decisions these tests pin:

1. "The agents are not treating each book as their own book" — halts are
   evaluated per book, and one tripped book must never speak for the
   others. (2026-08-27: primary at -8.0% froze the healthy 25k and 75k
   books for 1,162 vetoes.)
2. "We should not have a weekly kill limit that truly stops all trading;
   it should suspend the lane from making any crazy investment and
   tighten up the spread to make things work away from the loss." — a
   weekly trip is RECOVERY (suspend speculative lanes, half size, +10
   TCS, tighter stops), never a full stop. The DAILY limit stays a hard
   stop by Mike's explicit choice: it is the anti-spiral brake.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.paper.killswitch import (  # noqa: E402
    RECOVERY_SIZE_FACTOR, RECOVERY_STOP_FACTOR, RECOVERY_TCS_BUMP,
    evaluate, recovery_policy,
)


def _acct(**over) -> dict:
    """A healthy, mid-week account row."""
    base = {
        "trading_halted": False,
        "halt_scope": None,
        "halt_reason": None,
        "week_start_equity_usd": 10_000.0,
        "week_realized_pnl_usd": 0.0,
        "day_start_equity_usd": 10_000.0,
        "today_realized_pnl_usd": 0.0,
        "consecutive_losses": 0,
    }
    base.update(over)
    return base


# --- the weekly limit is recovery, never a stop --------------------------

def test_weekly_trip_is_recovery_not_halt():
    v = evaluate(_acct(week_realized_pnl_usd=-800.0))  # -8% of 10k
    assert v.halted is False, "weekly must not hard-stop the book"
    assert v.mode == "recovery"
    assert v.scope == "week"
    assert "recovery" in (v.reason or "").lower()


def test_weekly_clawback_ends_recovery_immediately():
    """Recovery is recomputed from row sums — earning back above the
    line clears it without waiting for Monday."""
    v = evaluate(_acct(week_realized_pnl_usd=-500.0))  # -5%, inside 6%
    assert v.halted is False and v.mode is None


def test_stale_persisted_weekly_halt_softens_to_recovery():
    """Rows written by the pre-08-27 behavior carry trading_halted=True
    with halt_scope='week'. They must read as recovery, not as a halt,
    so the change takes effect without waiting for the Monday roll."""
    v = evaluate(_acct(trading_halted=True, halt_scope="week",
                       halt_reason="Weekly loss limit: down $425"))
    assert v.halted is False
    assert v.mode == "recovery"


# --- the daily limit stays a hard stop (Mike's explicit choice) ----------

def test_daily_trip_still_hard_halts():
    v = evaluate(_acct(today_realized_pnl_usd=-400.0))  # -4% of 10k
    assert v.halted is True
    assert v.scope == "day"
    assert v.mode == "halt"


def test_losing_streak_still_hard_halts():
    v = evaluate(_acct(consecutive_losses=3))
    assert v.halted is True and v.mode == "halt"


def test_persisted_day_halt_still_reads_as_halt():
    v = evaluate(_acct(trading_halted=True, halt_scope="day",
                       halt_reason="Daily loss limit"))
    assert v.halted is True and v.mode == "halt"


def test_recovering_book_still_hard_halts_on_a_daily_trip():
    """KS-2: recovery must not disarm the anti-spiral brake. A book that
    is -8% on the week AND -4% today is HALTED (day), not merely in
    recovery — the weekly verdict used to return first and hide it."""
    v = evaluate(_acct(week_realized_pnl_usd=-800.0,
                       today_realized_pnl_usd=-400.0))
    assert v.halted is True
    assert v.scope == "day" and v.mode == "halt"


def test_recovering_book_still_hard_halts_on_a_streak():
    v = evaluate(_acct(week_realized_pnl_usd=-800.0, consecutive_losses=3))
    assert v.halted is True and v.mode == "halt"


# --- per-book independence: evaluate() sees ONE book's numbers -----------

def test_books_are_judged_on_their_own_numbers():
    """The 2026-08-27 shape: primary -8%, the other books barely down.
    Each row evaluates independently — only the tripped one changes."""
    primary = evaluate(_acct(week_start_equity_usd=5_300.0,
                             week_realized_pnl_usd=-424.0))
    b25 = evaluate(_acct(week_start_equity_usd=26_900.0,
                         week_realized_pnl_usd=-435.0))
    b75 = evaluate(_acct(week_start_equity_usd=80_000.0,
                         week_realized_pnl_usd=-2_200.0))
    assert primary.mode == "recovery"
    assert b25.halted is False and b25.mode is None
    assert b75.halted is False and b75.mode is None


# --- the "no crazy investments" list ------------------------------------

def test_speculative_lanes_are_suspended_in_recovery():
    for s in ("option_day", "stms", "stms_momentum", "orb",
              "orb_breakout", "crypto_scalp", "long_call", "long_put",
              "bull_call_spread", "butterfly"):
        assert recovery_policy(s) == "suspend", s


def test_working_lanes_keep_trading_tightened():
    for s in ("swing", "wheel_csp", "wheel_cc", "dividend_lt",
              "crypto_swing", "crypto_dca", "extended", "forex_swing",
              "", None):
        assert recovery_policy(s) == "tighten", s


def test_recovery_knobs_match_mikes_choice():
    """Half size, +10 TCS, stops 25% tighter — chosen explicitly
    2026-08-27. A drive-by 'tune' of these is a behavior change and
    needs the same sign-off."""
    assert RECOVERY_SIZE_FACTOR == 0.5
    assert RECOVERY_TCS_BUMP == 10
    assert RECOVERY_STOP_FACTOR == 0.75
