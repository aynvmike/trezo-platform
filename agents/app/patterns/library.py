"""All 12 candlestick pattern detection functions.

Each function returns a bool. They take either a single Candle, two
consecutive candles, three consecutive candles, or a sequence of candles
depending on the pattern.

Originally seeded by the founder's Codex `isHammer()` function — see
TREZO_PATTERN_ENGINE.md.
"""

from __future__ import annotations

from typing import Iterable

from .candle import Candle

# ===========================================================================
# Single-candle patterns
# ===========================================================================


def is_hammer(c: Candle) -> bool:
    """Founder's original. Small body, long lower wick, tiny upper wick.

    A bullish reversal signal when found at the bottom of a downtrend.
    """
    if c.range <= 0:
        return False
    return (
        c.body / c.range < 0.35
        and c.lower_wick >= c.body * 2
        and c.upper_wick <= c.body
    )


def is_inverted_hammer(c: Candle) -> bool:
    """Mirror of hammer. Long upper wick, tiny lower wick."""
    if c.range <= 0:
        return False
    return (
        c.body / c.range < 0.35
        and c.upper_wick >= c.body * 2
        and c.lower_wick <= c.body
    )


def is_doji(c: Candle) -> bool:
    """Body is tiny vs range — indecision."""
    return c.range > 0 and c.body / c.range < 0.05


def is_shooting_star(c: Candle) -> bool:
    """Like an inverted hammer, but the body is bearish — reversal off a high."""
    if c.range <= 0:
        return False
    return (
        c.body / c.range < 0.30
        and c.upper_wick >= c.body * 2
        and c.is_bearish
    )


# ===========================================================================
# Two-candle patterns
# ===========================================================================


def is_bullish_engulfing(prev: Candle, current: Candle) -> bool:
    """Previous bearish; current bullish + fully engulfs prev's body."""
    return (
        prev.is_bearish
        and current.is_bullish
        and current.open < prev.close
        and current.close > prev.open
    )


def is_bearish_engulfing(prev: Candle, current: Candle) -> bool:
    """Previous bullish; current bearish + fully engulfs prev's body."""
    return (
        prev.is_bullish
        and current.is_bearish
        and current.open > prev.close
        and current.close < prev.open
    )


def is_bullish_harami(prev: Candle, current: Candle) -> bool:
    """Previous bearish with big body; current bullish + inside prev's body."""
    return (
        prev.is_bearish
        and current.is_bullish
        and current.open > prev.close
        and current.close < prev.open
        and current.high < prev.high
        and current.low > prev.low
    )


# ===========================================================================
# Three-candle patterns
# ===========================================================================


def is_morning_star(c1: Candle, c2: Candle, c3: Candle) -> bool:
    """Bearish big body → small body → bullish big body closing past midpoint."""
    big_body_1 = c1.open - c1.close
    if big_body_1 <= 0:
        return False
    c1_bearish = c1.is_bearish
    c2_small = c2.body < big_body_1 * 0.3
    c3_bullish = c3.is_bullish
    c3_closes_high = c3.close > (c1.open + c1.close) / 2
    return c1_bearish and c2_small and c3_bullish and c3_closes_high


def is_evening_star(c1: Candle, c2: Candle, c3: Candle) -> bool:
    """Mirror of morning star."""
    big_body_1 = c1.close - c1.open
    if big_body_1 <= 0:
        return False
    c1_bullish = c1.is_bullish
    c2_small = c2.body < big_body_1 * 0.3
    c3_bearish = c3.is_bearish
    c3_closes_low = c3.close < (c1.open + c1.close) / 2
    return c1_bullish and c2_small and c3_bearish and c3_closes_low


def is_three_white_soldiers(c1: Candle, c2: Candle, c3: Candle) -> bool:
    """Three consecutive bullish candles, each closing higher, similar size,
    small upper wicks."""
    all_bullish = c1.is_bullish and c2.is_bullish and c3.is_bullish
    if not all_bullish:
        return False
    if not (c1.close < c2.close < c3.close):
        return False
    # body similar-size guard
    body_1 = c1.close - c1.open
    body_2 = c2.close - c2.open
    if body_1 <= 0:
        return False
    if abs(body_2 - body_1) / body_1 >= 0.5:
        return False
    # small upper wicks
    for c in (c1, c2, c3):
        body = c.close - c.open
        if body <= 0:
            return False
        if c.upper_wick >= body * 0.3:
            return False
    return True


def is_three_black_crows(c1: Candle, c2: Candle, c3: Candle) -> bool:
    """Mirror of Three White Soldiers."""
    all_bearish = c1.is_bearish and c2.is_bearish and c3.is_bearish
    if not all_bearish:
        return False
    if not (c1.close > c2.close > c3.close):
        return False
    body_1 = c1.open - c1.close
    body_2 = c2.open - c2.close
    if body_1 <= 0:
        return False
    if abs(body_2 - body_1) / body_1 >= 0.5:
        return False
    for c in (c1, c2, c3):
        body = c.open - c.close
        if body <= 0:
            return False
        if c.lower_wick >= body * 0.3:
            return False
    return True


# ===========================================================================
# Multi-candle structural pattern
# ===========================================================================


def is_cup_and_handle(candles: list[Candle], lookback: int = 40) -> bool:
    """U-shaped recovery (cup) followed by a small consolidation (handle).

    Bullish continuation. Needs at least `lookback` candles.
    """
    if len(candles) < lookback:
        return False

    window = candles[-lookback:]
    midpoint = lookback // 2
    left = window[:midpoint]
    right = window[midpoint:]

    cup_start = left[0].high
    cup_low = min(c.low for c in window[: int(lookback * 0.75)])
    cup_end = right[-1].close

    if cup_start <= 0 or cup_start - cup_low <= 0:
        return False

    cup_depth = (cup_start - cup_low) / cup_start
    recovery = (cup_end - cup_low) / (cup_start - cup_low)

    cup_valid = 0.10 < cup_depth < 0.50 and recovery > 0.85

    handle = candles[-5:]
    handle_high = max(c.high for c in handle)
    handle_low = min(c.low for c in handle)
    if handle[0].close <= 0:
        return False
    handle_range = (handle_high - handle_low) / handle[0].close
    handle_valid = handle_range < cup_depth * 0.3

    return cup_valid and handle_valid


# ===========================================================================
# Master detector — runs all patterns on a candle stream
# ===========================================================================


PATTERN_DIRECTION: dict[str, str] = {
    "Hammer":               "bullish",
    "Inverted_Hammer":      "bullish",
    "Bullish_Engulfing":    "bullish",
    "Bullish_Harami":       "bullish",
    "Morning_Star":         "bullish",
    "Three_White_Soldiers": "bullish",
    "Cup_And_Handle":       "bullish",
    "Bearish_Engulfing":    "bearish",
    "Evening_Star":         "bearish",
    "Three_Black_Crows":    "bearish",
    "Shooting_Star":        "bearish",
    "Doji":                 "neutral",
}


def detect_all(candles: Iterable[Candle]) -> dict[str, bool]:
    """Run every pattern detector on `candles` (most recent at end).

    Returns a dict of {pattern_name: detected?}.
    """
    cs = list(candles)
    out: dict[str, bool] = {}

    if len(cs) >= 1:
        last = cs[-1]
        out["Hammer"]          = is_hammer(last)
        out["Inverted_Hammer"] = is_inverted_hammer(last)
        out["Doji"]            = is_doji(last)
        out["Shooting_Star"]   = is_shooting_star(last)

    if len(cs) >= 2:
        prev, curr = cs[-2], cs[-1]
        out["Bullish_Engulfing"] = is_bullish_engulfing(prev, curr)
        out["Bearish_Engulfing"] = is_bearish_engulfing(prev, curr)
        out["Bullish_Harami"]    = is_bullish_harami(prev, curr)

    if len(cs) >= 3:
        c1, c2, c3 = cs[-3], cs[-2], cs[-1]
        out["Morning_Star"]         = is_morning_star(c1, c2, c3)
        out["Evening_Star"]         = is_evening_star(c1, c2, c3)
        out["Three_White_Soldiers"] = is_three_white_soldiers(c1, c2, c3)
        out["Three_Black_Crows"]    = is_three_black_crows(c1, c2, c3)

    out["Cup_And_Handle"] = is_cup_and_handle(cs)

    return out
