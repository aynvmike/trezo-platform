"""Market regime filter + symbol quality checks.

Phase 8d-8e, from TREZO_NOVA_BOT_TRADE_RULES.md Sections 2-4. Pre-trade
gates the Risk Manager applies to every stock signal:

  - Market direction: trade only with the broad market. Longs are blocked
    when both SPY and QQQ are below their session VWAP; shorts are blocked
    when both are above it.
  - Symbol liquidity: the name must trade above $5 and average over a
    million shares a day.
  - Overextension: a signal is rejected when price has stretched too far
    from its mean - the bot should not chase a parabolic move.

  - Spread / halt / data-quality: with the Alpaca market-data feed live
    (Data feed Part 1), a wide bid/ask spread or a missing quote during
    the session blocks the trade.

Crypto signals skip these gates - crypto trades 24/7 and is not tied to
the US equity session.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from app.patterns.indicators import vwap, avg_volume

MIN_PRICE = 0.0
MIN_AVG_VOLUME = 250_000  # fallback only; live default = settings.min_avg_volume (TREZO_MIN_AVG_VOLUME)
MAX_ATR_STRETCH = 4.0          # ATRs from the 20-day mean before "overextended"
MAX_SPREAD_PCT = 0.005         # widest bid/ask spread before a name is "illiquid"
_CACHE_TTL = 120.0

# Per-strategy liquidity floors. Each strategy has its own thesis on
# what "tradeable" means - STMS hunts small-caps where 1M shares/day is
# WAY too restrictive; the curated Wheel watchlist is pre-filtered so
# the floor only catches mistakes. The constants above remain the
# fallback for any strategy not listed here.
#
# Mike 2026-06-03: the platform-wide 1M floor was filtering everything
# out of STMS for days. Per-strategy floors fix the structural mismatch.
STRATEGY_LIQUIDITY_FLOORS: dict[str, dict[str, float]] = {
    # STMS - small-cap momentum, $1-$20 stocks, 5x-volume breakouts.
    # Low floors are the whole point of the strategy.
    "stms": {"min_price": 0.0, "min_avg_volume": 100_000},
    # ORB - opening range breakout. Needs decent participation but
    # doesn't require mega-cap liquidity.
    "orb": {"min_price": 0.0, "min_avg_volume": 500_000},
    # Extended - multi-day swing on EMA50 pullbacks. Wants the full
    # liquidity story so fills are clean across days.
    "extended": {"min_price": 0.0, "min_avg_volume": 500_000},
    # Pattern detection - flexible, runs on the watchlist + market pool.
    # 2026-06-16: dropped the hardcoded 1M floor (it vetoed ~all
    # market-wide names, leaving AAPL the only one trading). Now follows
    # the global tunable (settings.min_avg_volume, default 250k).
    "pattern": {"min_price": 0.0},
    # Wheel CSP / CC - the universe is curated (WHEEL_WATCHLIST) so the
    # floor is just a sanity check. Medium-high floor is fine because
    # the curated list already screens above this.
    "wheel_csp": {"min_price": 0.0, "min_avg_volume": 500_000},
    "wheel_cc": {"min_price": 0.0, "min_avg_volume": 500_000},
    # Cycle-aware strategies (Layer B). Inherit pattern's defaults until
    # we have outcome data to tune them.
    "iv_crush_short": {"min_price": 0.0, "min_avg_volume": 500_000},
    "dividend_capture_long": {"min_price": 0.0, "min_avg_volume": 500_000},
}


def _global_min_volume() -> float:
    """Tunable global liquidity floor. Reads settings.min_avg_volume
    (env TREZO_MIN_AVG_VOLUME); falls back to MIN_AVG_VOLUME if settings
    are unavailable. Added 2026-06-16 so the floor is no longer a static
    code constant (Mike's experience-driven-vetoes direction)."""
    try:
        from app.config import get_settings
        v = float(get_settings().min_avg_volume or 0)
        return v if v > 0 else float(MIN_AVG_VOLUME)
    except Exception:  # noqa: BLE001
        return float(MIN_AVG_VOLUME)


def _floors_for(strategy: str | None) -> tuple[float, float]:
    """Return (min_price, min_avg_volume) for the given strategy.
    Unmapped or empty strategy -> the global (tunable) defaults."""
    gmin = _global_min_volume()
    if not strategy:
        return MIN_PRICE, gmin
    floors = STRATEGY_LIQUIDITY_FLOORS.get(str(strategy).lower())
    if not floors:
        return MIN_PRICE, gmin
    return (
        float(floors.get("min_price", MIN_PRICE)),
        float(floors.get("min_avg_volume", gmin)),
    )


@dataclass
class MarketBias:
    bias: str                       # 'bullish' | 'bearish' | 'mixed' | 'unknown'
    spy_above_vwap: Optional[bool]
    qqq_above_vwap: Optional[bool]
    summary: str


_cache: Optional[MarketBias] = None
_cache_at: float = 0.0


async def _index_above_vwap(symbol: str) -> Optional[bool]:
    """True if `symbol`'s last price is above its session VWAP. None if no data."""
    try:
        from app.data.candles import fetch_stock_candles
        candles = await fetch_stock_candles(symbol, period="1d", interval="5m")
    except Exception:  # noqa: BLE001
        candles = []
    if not candles or len(candles) < 3:
        return None
    vw = vwap(candles)
    if not vw:
        return None
    return float(candles[-1].close) > float(vw[-1])


async def get_market_bias() -> MarketBias:
    """Classify the broad market from SPY + QQQ vs session VWAP. Cached 120s."""
    global _cache, _cache_at
    now = time.time()
    if _cache is not None and (now - _cache_at) < _CACHE_TTL:
        return _cache

    spy = await _index_above_vwap("SPY")
    qqq = await _index_above_vwap("QQQ")

    if spy is None and qqq is None:
        bias = MarketBias("unknown", None, None,
                          "Market data unavailable - direction filter is off.")
    else:
        ups = [x for x in (spy, qqq) if x is True]
        downs = [x for x in (spy, qqq) if x is False]
        if downs and not ups:
            bias = MarketBias("bearish", spy, qqq,
                              "SPY and QQQ below session VWAP - bearish.")
        elif ups and not downs:
            bias = MarketBias("bullish", spy, qqq,
                              "SPY and QQQ above session VWAP - bullish.")
        else:
            bias = MarketBias("mixed", spy, qqq,
                              "SPY and QQQ mixed vs VWAP - no clear bias.")
    _cache, _cache_at = bias, now
    return bias


def direction_blocked(bias: MarketBias, side: str) -> Optional[str]:
    """Return a veto reason if the broad market opposes the trade side."""
    if bias.bias == "bearish" and side == "long":
        return "Market filter: SPY and QQQ below VWAP - long trades blocked"
    if bias.bias == "bullish" and side == "short":
        return "Market filter: SPY and QQQ above VWAP - short trades blocked"
    return None


def liquidity_check(candles, strategy: str | None = None) -> Optional[str]:
    """Return a veto reason if the symbol fails the liquidity floor.

    Per-strategy floors per Mike's 2026-06-03 ask. The global constants
    MIN_PRICE / MIN_AVG_VOLUME stay as the fallback for any strategy
    not in STRATEGY_LIQUIDITY_FLOORS.
    """
    if not candles:
        return "No price data for the liquidity check"
    min_price, min_volume = _floors_for(strategy)
    price = float(candles[-1].close)
    if price < min_price:
        return (f"Liquidity filter [{strategy or 'default'}]: price "
                f"${price:.2f} is below the ${min_price:.0f} minimum")
    av = avg_volume(candles, 20)
    if av < min_volume:
        return (f"Liquidity filter [{strategy or 'default'}]: average "
                f"volume {av:,.0f} is below the {min_volume:,.0f}-share "
                f"minimum")
    return None


def profiles_accepting(candles) -> list[str]:
    """Which strategy liquidity profiles WOULD accept this symbol.

    Mike 2026-06-12 (mem0 72c35e29: YMAT, TCS 670, $1.23, vetoed by the
    $5 default floor while strategy='unknown'): a high-TCS signal that
    fails its OWN profile's floor may fit a different strategy's lane --
    YMAT is a textbook STMS candidate ($1-$20 small-cap momentum). This
    helper names the lanes that fit so the veto can carry reattribution
    candidates instead of throwing the information away."""
    if not candles:
        return []
    price = float(candles[-1].close)
    av = avg_volume(candles, 20)
    out: list[str] = []
    for name, floors in STRATEGY_LIQUIDITY_FLOORS.items():
        if (price >= float(floors.get("min_price", MIN_PRICE))
                and av >= float(floors.get("min_avg_volume", _global_min_volume()))):
            out.append(name)
    return out


def atr(candles, period: int = 14) -> float:
    """Average True Range over the last `period` bars."""
    if len(candles) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(candles)):
        h = float(candles[i].high)
        lo = float(candles[i].low)
        pc = float(candles[i - 1].close)
        trs.append(max(h - lo, abs(h - pc), abs(lo - pc)))
    recent = trs[-period:]
    return sum(recent) / len(recent) if recent else 0.0


def overextension_check(candles) -> Optional[str]:
    """Reject a signal when price has stretched too far from its 20-day
    mean, measured in ATRs - the bot should not chase a parabolic move."""
    if not candles or len(candles) < 21:
        return None
    cl = [float(c.close) for c in candles]
    price = cl[-1]
    sma20 = sum(cl[-20:]) / 20.0
    a = atr(candles, 14)
    if a <= 0 or sma20 <= 0:
        return None
    stretch = (price - sma20) / a
    if abs(stretch) > MAX_ATR_STRETCH:
        return (f"Overextended: price is {stretch:.1f} ATR from its 20-day "
                f"average - too stretched to chase")
    return None


async def spread_quality_check(ticker: str) -> Optional[str]:
    """Live bid/ask spread + halt / data-quality gate (Phase 8d, completed).

    Uses the Alpaca market-data feed. A wide spread means an illiquid name
    and high expected slippage; a missing bid/ask during the session is
    treated as a possible halt. Returns a veto reason, or None when the
    quote looks clean - or when no live feed is configured."""
    try:
        from app.brokers.alpaca_data import get_quote, market_data_available
    except Exception:  # noqa: BLE001
        return None
    if not market_data_available():
        return None
    q = await get_quote(ticker)
    if q is None:
        return None  # transient miss - never block trading on one
    if q.bid <= 0 or q.ask <= 0:
        return (f"{ticker}: no live bid/ask quote - possibly halted, "
                f"signal skipped")
    sp = q.spread_pct
    if sp > MAX_SPREAD_PCT:
        return (f"{ticker}: bid/ask spread {sp * 100:.2f}% is too wide "
                f"(limit {MAX_SPREAD_PCT * 100:.1f}%) - illiquid, skipped")
    return None
