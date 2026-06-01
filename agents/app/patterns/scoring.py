"""Trezo pattern scoring engine.

10-factor scoring → 0-100 base.
Trade Confidence Score scaling → 0-1000.

Founder's original 6 criteria (trend, momentum, MACD, volume, breakout,
candle) preserved. New: BB position, VWAP alignment, market alignment,
IV environment. Plus bonuses for multi-timeframe confluence and catalysts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .candle import Candle
from .indicators import (
    ema,
    rsi,
    macd as macd_fn,
    bollinger,
    vwap as vwap_fn,
    avg_volume,
    highest_high,
    closes,
)
from .library import detect_all, PATTERN_DIRECTION


# ---- Optional environment inputs ------------------------------------------


@dataclass
class MarketContext:
    """Optional context the score uses if provided.

    Pass None for any field we don't have data for.
    """

    spy_trending_up: Optional[bool] = None       # is_market_alignment
    iv_rank: Optional[float] = None              # 0..100 implied vol percentile
    catalyst_today: bool = False                 # news catalyst
    confluence_bonus: float = 0.0                # from multi-timeframe scan
    pattern_weights: Optional[dict] = None       # per-factor weight tilt


# ---- Output type ----------------------------------------------------------


@dataclass
class Score:
    score: int                                   # 0..100
    tcs: int                                     # 0..1000
    detected_patterns: list[str] = field(default_factory=list)
    breakdown: dict[str, float] = field(default_factory=dict)
    dominant_pattern: Optional[str] = None
    direction: str = "neutral"                   # 'bullish' | 'bearish' | 'neutral'


# Built-in fair-weighted Pattern Engine factor weights (sum 100).
# Users can override via MarketContext.pattern_weights (Bot Tuning ->
# Pattern factor weights). Missing keys fall back to these defaults.
DEFAULT_PATTERN_WEIGHTS: dict[str, int] = {
    "trend":            12,
    "momentum":         10,
    "macd":             12,
    "volume":           10,
    "breakout":         12,
    "candle_pattern":   10,
    "bb_position":       8,
    "vwap_alignment":    8,
    "market_alignment":  8,
    "iv_environment":   10,
}


def _merged_weights(ctx: MarketContext) -> dict[str, int]:
    """The active weight map for this scoring call."""
    if not ctx.pattern_weights:
        return DEFAULT_PATTERN_WEIGHTS
    merged = dict(DEFAULT_PATTERN_WEIGHTS)
    for k, v in (ctx.pattern_weights or {}).items():
        try:
            iv = int(v)
        except (TypeError, ValueError):
            continue
        if k in merged and 0 <= iv <= 30:
            merged[k] = iv
    return merged


# ---- Individual criteria --------------------------------------------------


def _criteria_trend(c: list[Candle]) -> bool:
    if len(c) < 50:
        return False
    cl = closes(c)
    e20 = ema(cl, 20)[-1]
    e50 = ema(cl, 50)[-1]
    return c[-1].close > e20 and e20 > e50


def _criteria_momentum(c: list[Candle]) -> bool:
    if len(c) < 15:
        return False
    r = rsi(closes(c), 14)[-1]
    return 50 < r < 70


def _criteria_macd(c: list[Candle]) -> bool:
    if len(c) < 35:
        return False
    m = macd_fn(closes(c))
    return m["hist"][-1] > 0 and m["macd"][-1] > m["signal"][-1]


def _criteria_volume(c: list[Candle]) -> bool:
    if len(c) < 21:
        return False
    avg20 = avg_volume(c[:-1], 20)
    return avg20 > 0 and c[-1].volume > avg20 * 1.5


def _criteria_breakout(c: list[Candle]) -> bool:
    if len(c) < 21:
        return False
    prior_high = highest_high(c[-21:-1])
    return c[-1].close > prior_high


def _criteria_candle_pattern(detections: dict[str, bool]) -> bool:
    return any(detections.values())


def _criteria_bb_position(c: list[Candle]) -> bool:
    """Price near lower band = bullish setup; near upper = bearish setup."""
    if len(c) < 20:
        return False
    bb = bollinger(closes(c), 20, 2.0)
    last = c[-1].close
    width = bb["upper"][-1] - bb["lower"][-1]
    if width <= 0:
        return False
    pct = (last - bb["lower"][-1]) / width   # 0 = at lower, 1 = at upper
    return pct < 0.25 or pct > 0.75          # extreme positioning


def _criteria_vwap_alignment(c: list[Candle]) -> bool:
    """Price respecting VWAP."""
    if len(c) < 5:
        return False
    v = vwap_fn(c)[-1]
    return abs(c[-1].close - v) / v < 0.02  # within 2%


def _criteria_market_alignment(ctx: MarketContext, direction: str) -> bool:
    if ctx.spy_trending_up is None:
        return False
    if direction == "bullish":
        return ctx.spy_trending_up
    if direction == "bearish":
        return not ctx.spy_trending_up
    return False


def _criteria_iv_environment(ctx: MarketContext) -> bool:
    """Reward when IV rank is reasonable for buying options (30-60)."""
    if ctx.iv_rank is None:
        return False
    return 30 <= ctx.iv_rank <= 60


# ---- Strategy-specific weighting (#123) -----------------------------------

# Base point value of each of the 10 criteria (their flat contribution).
_CRITERION_POINTS = {
    "trend": 12, "momentum": 10, "macd": 12, "volume": 10, "breakout": 12,
    "candle_pattern": 10, "bb_position": 8, "vwap_alignment": 8,
    "market_alignment": 8, "iv_environment": 10,
}

# Per-family multipliers. A family scores the factors it cares about
# higher and the ones it does not lower. Any criterion not listed = 1.0.
_FAMILY_WEIGHTS = {
    "trend": {"trend": 1.6, "macd": 1.4, "market_alignment": 1.4,
              "momentum": 1.1, "breakout": 0.7, "bb_position": 0.5},
    "breakout": {"breakout": 1.7, "volume": 1.5, "momentum": 1.2,
                 "trend": 1.1, "bb_position": 0.5, "vwap_alignment": 0.8},
    "momentum": {"momentum": 1.6, "volume": 1.5, "breakout": 1.3,
                 "macd": 1.2, "trend": 1.0, "bb_position": 0.5},
    "mean_reversion": {"bb_position": 1.8, "vwap_alignment": 1.5,
                       "momentum": 1.2, "trend": 0.5, "breakout": 0.4,
                       "macd": 0.8},
}

# Which family each Trezo strategy scores under.
STRATEGY_FAMILY = {
    "orb": "breakout",
    "stms": "momentum",
    "crypto": "momentum",
    "crypto_scalp": "momentum",
    "crypto_swing": "trend",
    "crypto_dca": "mean_reversion",
}


def _strategy_family(strategy: Optional[str]) -> Optional[str]:
    """Map a strategy name to its scoring family, or None to keep the
    flat (unweighted) score - the default for unmapped strategies."""
    if not strategy:
        return None
    s = str(strategy).lower()
    fam = STRATEGY_FAMILY.get(s) or STRATEGY_FAMILY.get(s.split("_")[0])
    return fam if fam in _FAMILY_WEIGHTS else None


def _weighted_core(breakdown: dict, family: str) -> float:
    """Re-weight the 10 base criteria for a strategy family, as a 0-100
    score - the share of weighted-possible points the signal earned."""
    weights = _FAMILY_WEIGHTS.get(family, {})
    earned = sum(pts * weights.get(k, 1.0)
                 for k, pts in _CRITERION_POINTS.items() if k in breakdown)
    possible = sum(pts * weights.get(k, 1.0)
                   for k, pts in _CRITERION_POINTS.items())
    return (earned / possible) * 100.0 if possible > 0 else 0.0


# ---- Main scorer ----------------------------------------------------------


def calculate_score(
    candles: list[Candle],
    context: Optional[MarketContext] = None,
    strategy: Optional[str] = None,
) -> Score:
    """Run all patterns + indicators and produce a Score."""
    ctx = context or MarketContext()
    detections = detect_all(candles)
    hit_patterns = [p for p, hit in detections.items() if hit]

    # Pick dominant pattern (priority: multi-candle > single-candle bullish > single bearish > neutral)
    priority = [
        "Three_White_Soldiers", "Three_Black_Crows",
        "Morning_Star", "Evening_Star",
        "Cup_And_Handle",
        "Bullish_Engulfing", "Bearish_Engulfing", "Bullish_Harami",
        "Hammer", "Inverted_Hammer", "Shooting_Star",
        "Doji",
    ]
    dominant: Optional[str] = next((p for p in priority if p in hit_patterns), None)
    direction = PATTERN_DIRECTION.get(dominant, "neutral") if dominant else "neutral"

    breakdown: dict[str, float] = {}
    score = 0.0
    _w = _merged_weights(ctx)

    if _criteria_trend(candles):
        score += _w["trend"]; breakdown["trend"] = _w["trend"]
    if _criteria_momentum(candles):
        score += _w["momentum"]; breakdown["momentum"] = _w["momentum"]
    if _criteria_macd(candles):
        score += _w["macd"]; breakdown["macd"] = _w["macd"]
    if _criteria_volume(candles):
        score += _w["volume"]; breakdown["volume"] = _w["volume"]
    if _criteria_breakout(candles):
        score += _w["breakout"]; breakdown["breakout"] = _w["breakout"]
    if _criteria_candle_pattern(detections):
        score += _w["candle_pattern"]; breakdown["candle_pattern"] = _w["candle_pattern"]
    if _criteria_bb_position(candles):
        score += _w["bb_position"]; breakdown["bb_position"] = _w["bb_position"]
    if _criteria_vwap_alignment(candles):
        score += _w["vwap_alignment"]; breakdown["vwap_alignment"] = _w["vwap_alignment"]
    if _criteria_market_alignment(ctx, direction):
        score += _w["market_alignment"]; breakdown["market_alignment"] = _w["market_alignment"]
    if _criteria_iv_environment(ctx):
        score += _w["iv_environment"]; breakdown["iv_environment"] = _w["iv_environment"]

    # Strategy-specific weighting (#123): re-weight the 10 criteria toward
    # what the signal's strategy family values. Unmapped strategies (and
    # plain pattern detection) keep the flat score, unchanged.
    fam = _strategy_family(strategy)
    core = _weighted_core(breakdown, fam) if fam else float(score)

    # Bonuses, applied on top of the (possibly re-weighted) core.
    if ctx.confluence_bonus > 0:
        core += ctx.confluence_bonus
        breakdown["confluence_bonus"] = ctx.confluence_bonus
    if ctx.catalyst_today:
        core += 15
        breakdown["catalyst"] = 15

    score_int = max(0, min(100, int(round(core))))
    return Score(
        score=score_int,
        tcs=scale_to_tcs(score_int, ctx),
        detected_patterns=hit_patterns,
        breakdown=breakdown,
        dominant_pattern=dominant,
        direction=direction,
    )


# ---- TCS scaling ----------------------------------------------------------


def scale_to_tcs(score_100: int, ctx: MarketContext) -> int:
    """Translate 0-100 pattern score into 0-1000 Trade Confidence Score.

    Allocation (from TREZO_PATTERN_ENGINE.md §4):
      - Technical (pattern):    300 max  ← from score_100
      - Options environment:    250 max  ← from IV rank
      - Fundamental/event:      200 max  ← catalyst signal
      - Risk/reward:            150 max  ← placeholder until Risk Manager wired
      - Market conditions:      100 max  ← SPY trending + confluence
    """
    technical = (score_100 / 100.0) * 300.0

    # Options environment: ideal IV rank between 30-60 gives full points,
    # taper outside that range
    if ctx.iv_rank is None:
        options = 100.0  # neutral default
    elif 30 <= ctx.iv_rank <= 60:
        options = 250.0
    elif ctx.iv_rank < 30:
        options = 250.0 * (ctx.iv_rank / 30.0)
    else:  # > 60
        options = 250.0 * max(0.0, (100.0 - ctx.iv_rank) / 40.0)

    fundamental = 200.0 if ctx.catalyst_today else 80.0
    rr = 120.0  # placeholder constant until Risk Manager is wired
    market = 50.0
    if ctx.spy_trending_up is True:
        market += 30.0
    if ctx.confluence_bonus >= 30:
        market += 20.0

    total = technical + options + fundamental + rr + market
    return max(0, min(1000, int(round(total))))
