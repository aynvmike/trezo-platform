"""Guard tests: a profit lock that cannot make money is not a profit lock.

Why these exist (2026-08-19). We measured the live crypto ladder against
30 days of real closed longs -- 90 trades, $112k of notional. It armed on
SIX of them and moved the month's P&L by $1.68. Two separate reasons, both
of which read as "working" from the outside:

  1. The rungs started at +5%. The median scalp/DCA peak on this book is
     ~0.58%, which is BELOW the 0.62% round-trip cost. The ladder was
     waiting for a move that mostly never comes.
  2. DCA's first rung locked +0.00%. Breakeven on crypto is a 0.62% LOSS.
     It had been shipping a losing exit labelled "profit locked" for two
     months and nothing in the system objected.

And one that would have silently eaten the fix: ladder_stop was fed the
monitor's 60-second tick price instead of the row's recorded peak, so a
rung only armed if a tick happened to land while price was above it. With
+5% rungs that rarely bit. With a +0.8% first rung it would have bitten
every day -- the retuned ladder would have looked deployed and done
nothing, which is the worst outcome of the three.

Run: python -m agents.tests.test_profit_ladder   (or pytest)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _bootstrap import load_module, run_tests, stub_config  # noqa: E402

stub_config()

cx = load_module("app.strategies.crypto")
cap = load_module("app.runtime.capabilities")

FEE_BPS = 26.0
SLIP_BPS = 5.0
ROUND_TRIP = cx.round_trip_cost_pct(FEE_BPS, SLIP_BPS)   # 0.0062

CRYPTO_LADDERS = {
    "SWING_PROFIT_LADDER": cx.SWING_PROFIT_LADDER,
    "DCA_PROFIT_LADDER": cx.DCA_PROFIT_LADDER,
}


# ---- the one that cost us two months -------------------------------------

def test_no_crypto_rung_locks_at_or_below_the_round_trip_cost():
    """A lock at or under 0.62% exits at a NET LOSS while the activity log
    says "profit locked". This is the exact bug DCA shipped with (+3% ->
    +0.00%). If a future edit reintroduces a breakeven rung, fail here and
    not in the P&L."""
    for name, ladder in CRYPTO_LADDERS.items():
        bad = cx.ladder_clears_fees(ladder, FEE_BPS, SLIP_BPS)
        assert not bad, (
            f"{name} has rung(s) locking at or under the {ROUND_TRIP:.4%} "
            f"round trip: {bad} -- each one books a loss labelled a profit")


def test_a_ladder_never_proposes_a_lower_lock_for_a_higher_peak():
    """The 6/13 SWING ladder went +5%->+0.00%, +8%->+3%, +10%->+5%: fine.
    But any dip in the locked column means a HIGHER peak proposes a LOWER
    stop, the ratchet refuses it, and the tier reads active while doing
    nothing."""
    for name, ladder in CRYPTO_LADDERS.items():
        assert cx.ladder_is_monotonic(ladder), (
            f"{name} is not strictly climbing in both columns: {ladder}")


def test_the_first_rung_arms_below_one_percent():
    """The whole finding of the 8/19 replay: 60 of 90 trades never reached
    +0.8%, and the +0.8% rung alone was worth $306 of the month while the
    +5% rung was worth $119. If someone widens the first rung back out,
    they should have to delete this test and read why."""
    for name, ladder in CRYPTO_LADDERS.items():
        first_trigger = float(ladder[0][0])
        assert first_trigger <= 0.010, (
            f"{name} first rung arms at {first_trigger:.2%}; above +1.0% it "
            f"misses the bulk of this book's moves (30-day replay, n=90)")


def test_the_gap_between_arming_and_locking_survives_ordinary_noise():
    """The replay scored a 0.65%/0.63% pair BEST and it is the worst real
    choice -- 0.02% of room, with $672 of realized profit standing behind
    it. The model cannot see a stop tripped early because it only knows
    entry, peak and exit, never the path. Mike picked +0.8%/+0.65% and
    +1.0%/+0.75% deliberately. Keep at least 0.10% of room."""
    for name, ladder in CRYPTO_LADDERS.items():
        for trigger, locked in ladder:
            gap = float(trigger) - float(locked)
            assert gap >= 0.0010, (
                f"{name} rung {trigger:.2%}->{locked:.2%} leaves {gap:.2%} of "
                f"room; a stop that close to its own trigger is tripped by noise")


# ---- the silent-failure one ----------------------------------------------

def test_ladder_stop_arms_from_the_peak_not_the_last_tick():
    """Not a test of ladder_stop (which is correctly pure) but of the
    contract the monitor must honour: given entry 100 and a peak of 101
    that has already pulled back to 100.2, the +0.8% rung IS reached.
    Feeding the tick price says "below rung one" and locks nothing."""
    ladder = cx.SWING_PROFIT_LADDER
    entry, peak, tick = 100.0, 101.0, 100.2

    from_tick = cap.ladder_stop(entry, tick, ladder, "long")
    from_peak = cap.ladder_stop(entry, max(tick, peak), ladder, "long")

    assert from_tick is None, (
        "sanity: +0.2% really is below the first rung")
    assert from_peak is not None, (
        "the peak reached +1.0% -- the ladder must arm on it")
    assert from_peak > entry * (1 + ROUND_TRIP), (
        "and what it arms must clear the round trip")


def test_a_ladder_stop_is_never_moved_down():
    """The ratchet, stated as a cost: a lock that fails to tighten gives up
    some upside; a lock that loosens gives up the position."""
    ladder = cx.SWING_PROFIT_LADDER
    entry = 100.0
    prev = 0.0
    for trigger, _locked in ladder:
        stop = cap.ladder_stop(entry, entry * (1 + float(trigger)), ladder, "long")
        assert stop is not None
        assert stop > prev, (
            f"peak +{trigger:.2%} proposed {stop}, which is not above the "
            f"previous rung's {prev} -- the ratchet would refuse it")
        prev = stop


def test_every_rung_locks_strictly_less_than_the_peak_that_armed_it():
    """A lock at or above its own trigger is an instant stop-out dressed as
    a profit lock."""
    for name, ladder in CRYPTO_LADDERS.items():
        for trigger, locked in ladder:
            assert float(locked) < float(trigger), (
                f"{name} rung {trigger:.2%}->{locked:.2%} locks at or above "
                f"the gain that armed it")


def test_a_peak_landing_exactly_on_a_rung_arms_it():
    """Found by this suite on 2026-08-19, in the live code. `gain >= trigger`
    on raw floats: entry 100.0, price 100.8 gives 0.007999999999999996, which
    is NOT >= 0.008, so the +0.8% rung did not arm. Same at +1.8%. Harmless
    when the rungs were +5% and +8%; with sub-1% rungs it is the difference
    between a ladder that works and one that ships, reports healthy and locks
    nothing."""
    ladder = cx.SWING_PROFIT_LADDER
    entry = 100.0
    for trigger, locked in ladder:
        exact = entry * (1.0 + float(trigger))
        stop = cap.ladder_stop(entry, exact, ladder, "long")
        assert stop is not None, (
            f"peak landed exactly on the +{trigger:.2%} rung and armed nothing")
        assert abs(stop - entry * (1.0 + float(locked))) < 1e-6, (
            f"peak exactly +{trigger:.2%} should lock +{locked:.2%}, got {stop}")


# ---- what we deliberately did NOT change ---------------------------------

def test_the_stock_ladder_was_not_retuned_on_crypto_evidence():
    """EXTENDED is equities, where Alpaca charges no commission, so its
    breakeven rung is genuinely breakeven rather than a hidden 0.62% loss.
    The 8/19 replay covered crypto longs only. If someone later applies the
    crypto rungs here, they are borrowing a conclusion from a different
    cost model."""
    assert cx.EXTENDED_PROFIT_LADDER[0] == (0.04, 0.00), (
        "EXTENDED_PROFIT_LADDER changed; it is stocks, and the crypto "
        "fee-floor argument does not apply to it")


if __name__ == "__main__":
    raise SystemExit(run_tests(globals()))
