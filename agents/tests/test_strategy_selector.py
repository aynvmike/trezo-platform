"""Unit tests for per-stock strategy selection (app.strategies.selector).

Covers the window gating that keeps the bot from picking a strategy
outside its trading window, and the select_strategy contract.

Run with:
    cd agents
    .\.venv\Scripts\python.exe -m pytest -q
"""

from datetime import datetime, timedelta, timezone

from app.patterns.candle import Candle
from app.patterns.scoring import MarketContext
from app.strategies.selector import (
    select_strategy,
    eligible_strategies,
    STOCK_STRATEGIES,
    CRYPTO_STRATEGIES,
)


def _series(n: int = 120, start: float = 100.0, drift: float = 0.012):
    """A deterministic candle series — a steady drift, no randomness."""
    out = []
    t0 = datetime(2025, 1, 1, tzinfo=timezone.utc)
    price = start
    for i in range(n):
        o = price
        price = price * (1 + drift)
        c = price
        h = max(o, c) * 1.004
        lw = min(o, c) * 0.996
        out.append(Candle(timestamp=t0 + timedelta(days=i),
                           open=o, high=h, low=lw, close=c, volume=1_000_000))
    return out


# ----- eligible_strategies: window gating -----------------------------------


def test_eligible_all_windows_open():
    got = eligible_strategies("stock", in_stms_window=True,
                              in_orb_window=True, in_swing_window=True)
    assert got == STOCK_STRATEGIES


def test_eligible_all_windows_closed():
    # STMS, ORB and Extended drop out; the always-on strategies remain.
    got = eligible_strategies("stock", in_stms_window=False,
                              in_orb_window=False, in_swing_window=False)
    assert got == ["default", "pattern"]
    assert "stms" not in got and "orb" not in got and "extended" not in got


def test_eligible_one_window_open():
    got = eligible_strategies("stock", in_stms_window=False,
                              in_orb_window=True, in_swing_window=False)
    assert "orb" in got
    assert "stms" not in got and "extended" not in got


def test_eligible_crypto_pool():
    got = eligible_strategies("crypto")
    assert got == CRYPTO_STRATEGIES
    assert "crypto" in got
    assert "stms" not in got and "orb" not in got


def test_eligible_never_empty():
    got = eligible_strategies("stock", in_stms_window=False,
                              in_orb_window=False, in_swing_window=False)
    assert got  # always a usable pool


# ----- select_strategy: contract --------------------------------------------


def test_select_picks_from_the_given_pool():
    pick = select_strategy(_series(), ctx=MarketContext(),
                           strategies=["default", "pattern"])
    assert pick.strategy in ("default", "pattern")
    assert len(pick.considered) == 2


def test_select_full_pool_shape():
    pick = select_strategy(_series(), ctx=MarketContext())
    assert pick.strategy in STOCK_STRATEGIES
    assert isinstance(pick.tcs, int)
    assert isinstance(pick.score, int)
    assert pick.direction in ("bullish", "bearish", "neutral")
    assert len(pick.considered) == len(STOCK_STRATEGIES)
    for c in pick.considered:
        assert {"strategy", "tcs", "direction", "backtest_return_pct"} <= set(c)
    assert pick.reason  # a plain-language explanation is always produced


def test_select_single_strategy_pool():
    pick = select_strategy(_series(), ctx=MarketContext(), strategies=["orb"])
    assert pick.strategy == "orb"
    assert len(pick.considered) == 1


def test_select_considered_sorted_by_tcs():
    pick = select_strategy(_series(), ctx=MarketContext())
    tcs_values = [c["tcs"] for c in pick.considered]
    assert tcs_values == sorted(tcs_values, reverse=True)
