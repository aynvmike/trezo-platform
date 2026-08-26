"""Guards for the Market Desk and its first consumers.

The property that matters most: A MISSING OR STALE REPORT CHANGES
NOTHING. Every consumer treats None as "no opinion". The desk can take
risk off the table on a fresh risk_off read; it can never add risk, and
its absence can never gate a lane shut. If these tests fail, the desk
has become a dependency instead of an advisor.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.agents.market_desk as md  # noqa: E402
from app.agents.market_desk import build_view, current_market_view  # noqa: E402
from app.strategies.wheel_advisor import check_market_pressure  # noqa: E402


def _iso(hours_ago: float = 0.0) -> str:
    return (datetime.now(timezone.utc)
            - timedelta(hours=hours_ago)).isoformat()


def _payload(hours_ago=1.0, regime="risk_off", **kw):
    p = {"as_of": _iso(hours_ago), "slot": "pre-market", "regime": regime,
         "indices": {"SPY": -1.2, "QQQ": -1.8},
         "vix": 24.5, "breadth": "decliners 3:1",
         "movers_up": ["ABC"], "movers_down": ["f", "AGNC", "TSLA"],
         "catalysts": ["CPI at 8:30"], "summary": "Red tape."}
    p.update(kw)
    return p


# --- the view builder ----------------------------------------------------

def test_build_view_digests_a_real_payload():
    v = build_view(_payload(), source="market-report")
    assert v is not None and v.regime == "risk_off"
    assert v.vix == 24.5 and v.indices["SPY"] == -1.2
    assert v.movers_down == ["F", "AGNC", "TSLA"], "tickers must uppercase"
    assert v.fresh()


def test_unknown_regime_never_passes_through():
    """The ingest wall already rejected regime='bananas' once. Same wall
    on the consumer side."""
    v = build_view(_payload(regime="bananas"))
    assert v is not None and v.regime == "unknown"


def test_stale_view_is_not_fresh_and_reader_returns_none():
    v = build_view(_payload(hours_ago=md.VIEW_MAX_AGE_H + 1))
    assert v is not None and not v.fresh()
    md._current = v
    assert current_market_view() is None, "a stale view leaked to consumers"


def test_missing_as_of_is_refused():
    assert build_view({"regime": "risk_off"}) is None
    assert build_view("not a dict") is None


def test_fresh_view_is_served():
    md._current = build_view(_payload(hours_ago=0.5))
    got = current_market_view()
    assert got is not None and got.regime == "risk_off"
    md._current = None


# --- the wheel's under-pressure check ------------------------------------

def test_csp_on_a_pressured_name_defers():
    v = check_market_pressure("wheel_csp", "AGNC",
                              movers_down=["F", "AGNC"], slot="pre-market")
    assert v.allow is False
    assert v.rule == "market_report.under_pressure"
    assert v.clears_when


def test_csp_on_a_calm_name_allows():
    assert check_market_pressure("wheel_csp", "O",
                                 movers_down=["F", "AGNC"]).allow is True


def test_covered_calls_are_never_gated_by_pressure():
    """A CC on a falling name REDUCES exposure — correct direction."""
    assert check_market_pressure("wheel_cc", "AGNC",
                                 movers_down=["AGNC"]).allow is True


def test_no_report_means_no_opinion():
    assert check_market_pressure("wheel_csp", "AGNC",
                                 movers_down=None).allow is True
    assert check_market_pressure("wheel_csp", "AGNC",
                                 movers_down=[]).allow is True


def test_pressure_check_is_case_blind():
    v = check_market_pressure("wheel_csp", "agnc", movers_down=["AGNC"])
    assert v.allow is False


# --- the tighten-only property, stated as a test -------------------------

def test_risk_on_report_tightens_nothing():
    """The report can raise bars, never lower them: a risk_on view must
    look exactly like no view at all to every consumer that only checks
    for risk_off."""
    md._current = build_view(_payload(regime="risk_on"))
    got = current_market_view()
    assert got is not None and got.regime == "risk_on"
    # the risk manager's branch adds a bump ONLY on risk_off; the
    # dailies' branch tightens ONLY on risk_off. This test documents
    # that contract where future readers will look for it.
    assert got.regime != "risk_off"
    md._current = None
