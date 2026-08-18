"""Guard tests: one book's Bot Tuning may not decide for another's.

The bug (Mike, 2026-08-18): "I also do not think the agents are
responding to each book's own setting." Scanners run once for the
platform and read get_bot_settings() with NO argument -- the global row.
A scanner signal carries no user_id, so Risk Manager's TCS check
resolved to that same global row. Trade Execution then fanned the
approved signal out to every book. Three books, one opinion: crypto off
on the 25k did nothing, because the primary's crypto_enabled was what
the scanner read.

Run: python -m agents.tests.test_book_gate   (or pytest)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _bootstrap import load_module, run_tests, stub_config  # noqa: E402

stub_config(trezo_crypto_tcs_floor=35)
gate = load_module("app.runtime.book_gate")


class Book:
    """A stand-in for one book's BotSettings row."""

    def __init__(self, **kw):
        self.auto_trade_enabled = True
        self.crypto_enabled = True
        self.extended_enabled = True
        self.stms_enabled = True
        self.pattern_enabled = True
        self.tcs_threshold = 70
        for k, v in kw.items():
            setattr(self, k, v)


def test_each_book_answers_for_itself():
    """The whole point: same signal, three books, three answers."""
    crypto = dict(asset_type="crypto", strategy="crypto_dca", tcs=60)
    stock = dict(asset_type="stock", strategy="swing", tcs=80)
    primary = Book()
    twentyfive = Book(crypto_enabled=False)
    seventyfive = Book(tcs_threshold=90)

    assert gate.admits(primary, **crypto).ok is True
    assert gate.admits(twentyfive, **crypto).ok is False
    assert gate.admits(primary, **stock).ok is True
    assert gate.admits(seventyfive, **stock).ok is False


def test_a_book_cannot_currently_tighten_crypto_with_its_slider():
    """Recorded because it surprised me writing the test above, not
    because it is obviously right.

    The crypto carve-out is min(slider, 35), so raising a book's TCS
    slider to 90 does nothing to crypto -- 35 still wins. That mirrors
    Risk Manager exactly, and disagreeing with the approval a signal
    came through would reject every crypto trade. But it does mean the
    slider is a stock-only control today. If Mike wants per-book crypto
    selectivity, that needs its own setting, in both places."""
    b = Book(tcs_threshold=90)
    assert gate.min_tcs_for(b, "crypto_dca") == 35
    assert gate.admits(b, asset_type="crypto",
                       strategy="crypto_dca", tcs=40).ok is True


def test_a_book_with_auto_trade_off_still_feeds_the_learning_loop():
    """Post-mortem learns from would_have_traded rows. A book sitting
    out has to keep producing them, or observe-only books quietly stop
    teaching the bot anything -- a regression that surfaces months later
    as 'it got worse' with nothing in the logs."""
    v = gate.admits(Book(auto_trade_enabled=False),
                    asset_type="stock", strategy="swing", tcs=90)
    assert v.ok is False
    assert v.event == "would_have_traded"


def test_a_declined_book_says_which_toggle():
    v = gate.admits(Book(stms_enabled=False),
                    asset_type="stock", strategy="orb_open", tcs=90)
    assert v.ok is False and v.event == "book_declined"
    assert "stms_enabled" in v.reason


def test_the_crypto_floor_carve_out_matches_the_approval_it_came_through():
    """Risk Manager approves crypto against min(slider, crypto floor).
    If this gate used the raw slider it would reject every crypto signal
    that just passed -- a book that looks enabled and never trades."""
    b = Book(tcs_threshold=70)
    assert gate.min_tcs_for(b, "crypto_swing") == 35
    assert gate.min_tcs_for(b, "swing") == 70
    assert gate.admits(b, asset_type="crypto",
                       strategy="crypto_swing", tcs=40).ok is True


def test_a_lower_slider_still_wins_over_the_carve_out():
    assert gate.min_tcs_for(Book(tcs_threshold=20), "crypto_dca") == 20


def test_an_unreadable_settings_row_fails_open():
    """A settings blip must not freeze a book. The historical behaviour
    was to trade; a gate that turns a transient error into a halt is
    worse than the leak it was written to close."""
    class Exploding:
        def __getattr__(self, name):
            raise RuntimeError("supabase blip")

    assert gate.admits(Exploding(), asset_type="stock",
                       strategy="swing", tcs=90).ok is True


def test_no_signal_reaches_the_fan_out_ungated_by_accident():
    """A strategy with no gate is admitted everywhere. That is the right
    default -- a new strategy must not be secretly disabled -- but it
    should be a decision. This is the list; adding to it is how it stays
    one."""
    ungated = [(at, st) for at, st in (
        ("crypto", "crypto_dca"), ("crypto", "crypto_hodl"),
        ("forex", "forex_trend"), ("stock", "orb_open"),
        ("stock", "stms_scalp"), ("stock", "pattern_breakout"),
        ("stock", "extended_gap"),
    ) if gate.ungated(at, st)]
    assert not ungated, f"no toggle governs: {ungated}"
    # Deliberately ungated today, recorded so it is visible:
    assert gate.ungated("stock", "swing") is True
    assert gate.ungated("option", "wheel_csp") is True


def test_a_toggle_only_gates_what_it_names():
    """crypto_enabled must not silence stocks."""
    b = Book(crypto_enabled=False)
    assert gate.admits(b, asset_type="stock", strategy="swing", tcs=90).ok
    assert not gate.admits(b, asset_type="crypto",
                           strategy="crypto_dca", tcs=90).ok


if __name__ == "__main__":
    sys.exit(run_tests(dict(globals())))
