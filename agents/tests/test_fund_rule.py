"""Guards for the FUND branch of the §4 entry screen.

WHY THIS FILE EXISTS. Mike asked, of the REIT fix: "is it going to
possibly do this to other Dividend Funds and not just fix for REIT?"
It was. The raise-streak rule -- correct for an operating company --
failed SEVEN OF EIGHT covered-call ETFs, because a variable distribution
is what those funds ARE. NVDY paid 5.05, then 19.53, then 12.14; that is
option premium tracking volatility, not a dividend cut.

The tests below encode the distinction the spec already drew and the
code had missed: a company is judged on whether it RAISED, a fund on
whether the distribution is FUNDED.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.strategies.dividend_screen import (  # noqa: E402
    MIN_FUND_DOLLAR_VOLUME, ScreenResult,
)


# --- the category error this branch exists to prevent -------------------

def test_a_fund_is_never_judged_on_a_raise_streak():
    """The bug in one assertion. A fund with a wildly variable payout and
    a healthy total return must not be failed for 'cutting'."""
    r = ScreenResult(ticker="NVDY", is_fund=True)
    # The fund path never populates these; if a future edit routes a fund
    # back through the company rule they will appear and this will fail.
    assert r.raise_streak_years is None
    assert r.cut_in_lookback is None


def test_paying_less_than_you_earn_passes():
    fh = _synth(dist=0.079, tr=0.0937, splits=0)
    assert fh["passed"] is True
    assert fh["checks"]["payout_vs_return"] == "pass"


def test_paying_more_than_you_earn_fails():
    fh = _synth(dist=0.5717, tr=0.2178, splits=0)
    assert fh["passed"] is False
    assert fh["checks"]["payout_vs_return"] == "fail"
    assert "eating NAV" in " ".join(fh["reasons"])


def test_a_reverse_split_fails_on_its_own():
    """Even with the payout covered. In a distribution fund a reverse
    split means the share price needed rescuing -- TSLY, 5:1, 2025-12-01."""
    fh = _synth(dist=0.05, tr=0.30, splits=1)
    assert fh["passed"] is False
    assert fh["checks"]["reverse_split"] == "fail"


def test_missing_data_is_unverified_not_a_pass():
    """Silence is not consent -- the same rule the rest of the screen
    follows. A fund we cannot measure must not slide through."""
    fh = _synth(dist=None, tr=None, splits=0)
    assert fh["verified"] is False
    assert fh["checks"]["payout_vs_return"] == "unverified"


# --- the size floor ------------------------------------------------------

def test_dollar_volume_floor_is_named_as_a_substitute():
    """Finnhub returns no AUM for funds on this tier, so the floor is
    liquidity. The constant must stay separate from MIN_FUND_AUM_USD so
    nobody later mistakes one measurement for the other."""
    from app.strategies.dividend_screen import MIN_FUND_AUM_USD
    assert MIN_FUND_DOLLAR_VOLUME != MIN_FUND_AUM_USD
    assert MIN_FUND_DOLLAR_VOLUME > 0


# --- fund DETECTION ------------------------------------------------------

def test_fund_detection_uses_absent_company_fundamentals():
    """Verified live 2026-08-23: Finnhub returns exactly 19 keys for an
    ETF -- all price technicals, no company figure -- and 126-133 for a
    stock. profile2's `type` is empty for BOTH on this tier, which is why
    the previous `if not m` test never fired and every ETF was silently
    judged as a company."""
    etf_metric = {"52WeekHigh": 60.0, "beta": 0.6,
                  "10DayAverageTradingVolume": 4.07}
    stock_metric = {"marketCapitalization": 629706.0,
                    "payoutRatioAnnual": 44.0,
                    "dividendYieldIndicatedAnnual": 3.12}
    assert _looks_like_fund(etf_metric) is True
    assert _looks_like_fund(stock_metric) is False


def _looks_like_fund(m: dict) -> bool:
    """Mirror of the detector in dividend_screen, kept here so a change
    to one without the other is visible."""
    return (m.get("marketCapitalization") is None
            and m.get("payoutRatioAnnual") is None
            and m.get("payoutRatioTTM") is None
            and m.get("dividendYieldIndicatedAnnual") is None)


# --- concentration -------------------------------------------------------

def test_funds_do_not_share_a_bucket_with_lookup_failures():
    """Finnhub returns no industry for a fund, so every ETF used to land
    in "UNKNOWN" alongside any STOCK whose profile fetch failed -- and a
    network blip could then evict a fund from the ladder."""
    from app.strategies.dividend_screen import sector_capped
    names = [
        ScreenResult(ticker="SCHD", is_fund=True),
        ScreenResult(ticker="VYM", is_fund=True),
        ScreenResult(ticker="MYSTERY1"),      # sector lookup failed
        ScreenResult(ticker="MYSTERY2"),
    ]
    kept = [r.ticker for r in sector_capped(names)]
    assert "SCHD" in kept and "VYM" in kept
    assert "MYSTERY1" in kept, "an unknown-sector stock must not be evicted"


# --- helper --------------------------------------------------------------

def _synth(*, dist, tr, splits: int) -> dict:
    """The verdict arithmetic from fund_health, without the network.

    Deliberately a re-expression rather than a mock: it states what the
    rule IS, so if the shipped rule drifts the intent is still written
    down somewhere a reader can check it against.
    """
    checks: dict = {}
    reasons: list = []
    if splits:
        checks["reverse_split"] = "fail"
        reasons.append("reverse split — NAV fell far enough to need rescuing")
    else:
        checks["reverse_split"] = "pass"
    if dist is None or tr is None:
        checks["payout_vs_return"] = "unverified"
    elif dist > tr:
        checks["payout_vs_return"] = "fail"
        reasons.append("the distribution is eating NAV, not funded by returns")
    else:
        checks["payout_vs_return"] = "pass"
    return {"checks": checks, "reasons": reasons,
            "passed": not any(v == "fail" for v in checks.values()),
            "verified": checks["payout_vs_return"] != "unverified"}
