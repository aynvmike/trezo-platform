"""Trezo Pattern Detection Engine.

Built on the founder's original Codex hammer/scoring code (see
TREZO_PATTERN_ENGINE.md). Expanded to 12 patterns + multi-timeframe
confluence + 10-factor scoring + Trade Confidence Score (0-1000).
"""

from .candle import Candle
from .library import (
    detect_all,
    is_hammer,
    is_inverted_hammer,
    is_doji,
    is_bullish_engulfing,
    is_bearish_engulfing,
    is_morning_star,
    is_evening_star,
    is_three_white_soldiers,
    is_three_black_crows,
    is_shooting_star,
    is_bullish_harami,
    is_cup_and_handle,
)

__all__ = [
    "Candle",
    "detect_all",
    "is_hammer",
    "is_inverted_hammer",
    "is_doji",
    "is_bullish_engulfing",
    "is_bearish_engulfing",
    "is_morning_star",
    "is_evening_star",
    "is_three_white_soldiers",
    "is_three_black_crows",
    "is_shooting_star",
    "is_bullish_harami",
    "is_cup_and_handle",
]
