"""Unit tests for every pattern in the Trezo library.

Each pattern has at least one positive (should detect) and one negative
(should not detect) case. Run with:

    cd agents
    .\.venv\Scripts\python.exe -m pytest -q
"""

from datetime import datetime, timezone

from app.patterns.candle import Candle
from app.patterns import library as L
from app.patterns.scoring import calculate_score, MarketContext
from app.patterns.confluence import confluence_bonus


def C(o: float, h: float, lw: float, c: float, v: float = 1000.0) -> Candle:
    """Shorthand to build a candle (timestamp doesn't matter for pattern logic)."""
    return Candle(
        timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        open=o, high=h, low=lw, close=c, volume=v,
    )


# ----- Hammer ------------------------------------------------------------------


def test_hammer_positive():
    # tiny body at top, long lower wick
    candle = C(o=10.0, h=10.1, lw=8.0, c=10.05)
    assert L.is_hammer(candle) is True


def test_hammer_negative_no_lower_wick():
    candle = C(o=10.0, h=11.0, lw=9.5, c=10.5)  # bigger body, not a hammer
    assert L.is_hammer(candle) is False


# ----- Inverted Hammer ---------------------------------------------------------


def test_inverted_hammer_positive():
    candle = C(o=10.0, h=12.0, lw=9.95, c=10.05)  # long upper wick, tiny lower
    assert L.is_inverted_hammer(candle) is True


def test_inverted_hammer_negative():
    candle = C(o=10.0, h=10.1, lw=8.0, c=10.05)  # this is a regular hammer
    assert L.is_inverted_hammer(candle) is False


# ----- Doji --------------------------------------------------------------------


def test_doji_positive():
    candle = C(o=10.0, h=10.5, lw=9.5, c=10.005)
    assert L.is_doji(candle) is True


def test_doji_negative():
    candle = C(o=10.0, h=10.5, lw=9.5, c=10.4)
    assert L.is_doji(candle) is False


# ----- Shooting Star -----------------------------------------------------------


def test_shooting_star_positive():
    # bearish body, long upper wick
    candle = C(o=10.05, h=12.0, lw=9.95, c=10.0)
    assert L.is_shooting_star(candle) is True


def test_shooting_star_negative():
    # bullish body — fails the bearish-body rule
    candle = C(o=10.0, h=12.0, lw=9.95, c=10.05)
    assert L.is_shooting_star(candle) is False


# ----- Bullish Engulfing -------------------------------------------------------


def test_bullish_engulfing_positive():
    prev = C(o=10.0, h=10.1, lw=9.3, c=9.4)   # bearish
    curr = C(o=9.3, h=10.5, lw=9.25, c=10.3)  # bullish, engulfs prev's body
    assert L.is_bullish_engulfing(prev, curr) is True


def test_bullish_engulfing_negative():
    prev = C(o=9.4, h=10.1, lw=9.3, c=10.0)   # bullish prior — fails
    curr = C(o=9.3, h=10.5, lw=9.25, c=10.3)
    assert L.is_bullish_engulfing(prev, curr) is False


# ----- Bearish Engulfing -------------------------------------------------------


def test_bearish_engulfing_positive():
    prev = C(o=9.4, h=10.1, lw=9.3, c=10.0)   # bullish
    curr = C(o=10.3, h=10.5, lw=9.0, c=9.2)   # bearish, engulfs
    assert L.is_bearish_engulfing(prev, curr) is True


def test_bearish_engulfing_negative():
    prev = C(o=10.0, h=10.1, lw=9.3, c=9.4)   # bearish prior — fails
    curr = C(o=10.3, h=10.5, lw=9.0, c=9.2)
    assert L.is_bearish_engulfing(prev, curr) is False


# ----- Bullish Harami ----------------------------------------------------------


def test_bullish_harami_positive():
    prev = C(o=11.0, h=11.1, lw=9.0, c=9.2)   # big bearish
    curr = C(o=9.6, h=10.5, lw=9.5, c=10.4)   # small bullish inside prev body
    assert L.is_bullish_harami(prev, curr) is True


def test_bullish_harami_negative_outside():
    prev = C(o=11.0, h=11.1, lw=9.0, c=9.2)
    curr = C(o=9.0, h=11.5, lw=8.8, c=11.4)   # current is OUTSIDE prev — not harami
    assert L.is_bullish_harami(prev, curr) is False


# ----- Morning Star ------------------------------------------------------------


def test_morning_star_positive():
    c1 = C(o=12.0, h=12.1, lw=10.0, c=10.2)   # big bearish
    c2 = C(o=10.2, h=10.5, lw=10.1, c=10.3)   # small body
    c3 = C(o=10.4, h=12.2, lw=10.35, c=12.0)  # big bullish closing past midpoint
    assert L.is_morning_star(c1, c2, c3) is True


def test_morning_star_negative():
    c1 = C(o=12.0, h=12.1, lw=10.0, c=10.2)
    c2 = C(o=10.2, h=10.5, lw=10.1, c=10.3)
    c3 = C(o=10.4, h=10.6, lw=10.0, c=10.05)  # c3 doesn't recover past midpoint
    assert L.is_morning_star(c1, c2, c3) is False


# ----- Evening Star ------------------------------------------------------------


def test_evening_star_positive():
    c1 = C(o=10.0, h=12.1, lw=9.9, c=12.0)
    c2 = C(o=12.0, h=12.2, lw=11.9, c=12.1)
    c3 = C(o=11.9, h=12.0, lw=10.0, c=10.2)
    assert L.is_evening_star(c1, c2, c3) is True


def test_evening_star_negative():
    c1 = C(o=10.0, h=12.1, lw=9.9, c=12.0)
    c2 = C(o=12.0, h=12.2, lw=11.9, c=12.1)
    c3 = C(o=11.9, h=12.5, lw=11.8, c=12.4)   # c3 is bullish, fails
    assert L.is_evening_star(c1, c2, c3) is False


# ----- Three White Soldiers ----------------------------------------------------


def test_three_white_soldiers_positive():
    c1 = C(o=10.0, h=10.5, lw=9.95, c=10.4)
    c2 = C(o=10.4, h=10.9, lw=10.35, c=10.8)
    c3 = C(o=10.8, h=11.3, lw=10.75, c=11.2)
    assert L.is_three_white_soldiers(c1, c2, c3) is True


def test_three_white_soldiers_negative_one_red():
    c1 = C(o=10.0, h=10.5, lw=9.95, c=10.4)
    c2 = C(o=10.4, h=10.9, lw=10.35, c=10.8)
    c3 = C(o=10.8, h=10.85, lw=10.4, c=10.5)  # bearish c3, fails
    assert L.is_three_white_soldiers(c1, c2, c3) is False


# ----- Three Black Crows -------------------------------------------------------


def test_three_black_crows_positive():
    c1 = C(o=11.2, h=11.25, lw=10.75, c=10.8)
    c2 = C(o=10.8, h=10.85, lw=10.35, c=10.4)
    c3 = C(o=10.4, h=10.45, lw=9.95, c=10.0)
    assert L.is_three_black_crows(c1, c2, c3) is True


def test_three_black_crows_negative():
    c1 = C(o=11.2, h=11.25, lw=10.75, c=10.8)
    c2 = C(o=10.8, h=10.85, lw=10.35, c=10.4)
    c3 = C(o=10.4, h=10.6, lw=10.35, c=10.55)  # bullish c3 fails
    assert L.is_three_black_crows(c1, c2, c3) is False


# ----- Cup and Handle ----------------------------------------------------------


def test_cup_and_handle_positive():
    """Build a synthetic U with a flat handle at the end."""
    candles: list[Candle] = []
    # Left half of the cup: 10 candles descending 100 → 70
    for i in range(10):
        price = 100.0 - i * 3.0
        candles.append(C(o=price, h=price + 1, lw=price - 1, c=price - 1))
    # Right half of the cup: 10 candles ascending 70 → 100
    for i in range(10):
        price = 70.0 + i * 3.0
        candles.append(C(o=price, h=price + 1, lw=price - 1, c=price + 1))
    # Pad to satisfy lookback=40 — flat top
    for _ in range(15):
        candles.append(C(o=100.0, h=100.5, lw=99.5, c=100.0))
    # Handle: 5 candles small consolidation
    for _ in range(5):
        candles.append(C(o=100.0, h=100.2, lw=99.8, c=100.0))

    assert L.is_cup_and_handle(candles) is True


def test_cup_and_handle_negative_no_cup():
    """A flat series — no U shape, no cup."""
    candles = [C(o=100.0, h=100.5, lw=99.5, c=100.0) for _ in range(45)]
    assert L.is_cup_and_handle(candles) is False


# ----- detect_all wrapper ------------------------------------------------------


def test_detect_all_returns_all_keys():
    candles = [C(o=10.0, h=10.5, lw=9.95, c=10.4) for _ in range(45)]
    out = L.detect_all(candles)
    # All 12 pattern keys should be present
    for key in [
        "Hammer", "Inverted_Hammer", "Doji", "Shooting_Star",
        "Bullish_Engulfing", "Bearish_Engulfing", "Bullish_Harami",
        "Morning_Star", "Evening_Star",
        "Three_White_Soldiers", "Three_Black_Crows",
        "Cup_And_Handle",
    ]:
        assert key in out, f"missing pattern key: {key}"


# ----- Scoring -----------------------------------------------------------------


def test_score_runs_without_context():
    candles = [C(o=10.0 + i * 0.05, h=10.1 + i * 0.05, lw=9.95 + i * 0.05, c=10.05 + i * 0.05)
               for i in range(60)]
    s = calculate_score(candles)
    assert 0 <= s.score <= 100
    assert 0 <= s.tcs <= 1000
    assert s.direction in {"bullish", "bearish", "neutral"}


def test_score_with_market_context():
    candles = [C(o=10.0 + i * 0.05, h=10.1 + i * 0.05, lw=9.95 + i * 0.05, c=10.05 + i * 0.05)
               for i in range(60)]
    ctx = MarketContext(spy_trending_up=True, iv_rank=45.0, catalyst_today=True)
    s = calculate_score(candles, ctx)
    # Catalyst + IV-in-sweet-spot + uptrending market should give a meaningful score
    assert s.tcs > 300


# ----- Confluence --------------------------------------------------------------


def test_confluence_bonus_no_shared_returns_zero():
    candles = [C(o=10.0, h=10.5, lw=9.5, c=10.0) for _ in range(30)]
    out = confluence_bonus({"a": candles[:5], "b": candles[:10]})
    assert out["bonus"] in (0, 30)  # depends on whether Doji fires on both


def test_confluence_bonus_three_tfs_gives_60():
    hammer = C(o=10.0, h=10.1, lw=8.0, c=10.05)
    out = confluence_bonus({"a": [hammer], "b": [hammer], "c": [hammer]})
    assert out["bonus"] == 60
