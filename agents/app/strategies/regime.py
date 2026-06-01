"""Market Regime Classifier.

Phase 7.5. Reads a broad-market proxy (SPY by default) and classifies the
market into one of the six regimes the Strategy Library understands:

    trending_up, trending_down, choppy,
    high_volatility, low_volatility, risk_off

The Adaptive Scope engine uses this read — together with the library's
REGIME_PLAYBOOK — to decide which strategy families to favor, trade
smaller, or pause.

The classifier is intentionally simple and deterministic: trend is read
from price vs its 50-day average and that average's slope; volatility
from the annualized standard deviation of recent daily returns versus the
window baseline; stress from drawdown off the recent peak.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict

from app.patterns import Candle
from app.patterns.indicators import sma, closes as _closes
from app.strategies import library


# Thresholds — annualized volatility is daily stdev * sqrt(252).
HIGH_VOL = 0.26
LOW_VOL = 0.12
VOL_SPIKE_RATIO = 1.6      # recent vol this many times the window baseline
RISK_OFF_DRAWDOWN = -0.08  # 8% off the recent peak
TREND_BAND = 0.01          # within +/-1% of the 50-day average counts as flat

DEFAULT_PROXY = "SPY"
MIN_CANDLES = 25


@dataclass(frozen=True)
class RegimeRead:
    regime: str
    confidence: float          # 0..1
    proxy: str
    trend_pct: float           # price vs the 50-day average
    slope_pct: float           # 50-day average slope, ~2 weeks
    annualized_vol: float      # recent realized volatility
    vol_ratio: float           # recent vol / window baseline
    drawdown_pct: float        # off the recent peak
    summary: str

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def playbook(self):
        return library.playbook_for(self.regime)


def _returns(values: list[float]) -> list[float]:
    out: list[float] = []
    for i in range(1, len(values)):
        prev = values[i - 1]
        if prev:
            out.append((values[i] - prev) / prev)
    return out


def _stdev(xs: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mean = sum(xs) / n
    var = sum((x - mean) ** 2 for x in xs) / n
    return math.sqrt(var)


def _confidence(
    regime: str, trend_pct: float, slope_pct: float,
    ann_vol: float, vol_ratio: float, drawdown_pct: float,
) -> float:
    if regime in ("trending_up", "trending_down"):
        mag = (min(abs(trend_pct) / 0.05, 1.0) * 0.5
               + min(abs(slope_pct) / 0.04, 1.0) * 0.5)
    elif regime == "risk_off":
        mag = min(abs(drawdown_pct) / 0.15, 1.0)
    elif regime == "high_volatility":
        mag = min((ann_vol - HIGH_VOL) / 0.15 + max(0.0, vol_ratio - 1.0), 1.0)
    elif regime == "low_volatility":
        mag = min((LOW_VOL - ann_vol) / 0.06 + 0.4, 1.0)
    else:  # choppy
        mag = 0.3
    return max(0.5, min(0.95, 0.5 + 0.45 * max(0.0, mag)))


def _summary(regime: str, trend_pct: float, ann_vol: float, drawdown_pct: float) -> str:
    play = library.playbook_for(regime)
    base = play.summary if play else regime
    vol_txt = f"{ann_vol * 100:.0f}% annualized volatility"
    if regime in ("trending_up", "trending_down"):
        return (f"{base} Price is {trend_pct * 100:+.1f}% vs its 50-day "
                f"average, {vol_txt}.")
    if regime == "risk_off":
        return (f"{base} Down {abs(drawdown_pct) * 100:.0f}% from the recent "
                f"peak, {vol_txt}.")
    return f"{base} ({vol_txt})."


def classify_regime(candles: list[Candle], proxy: str = DEFAULT_PROXY) -> RegimeRead:
    """Classify a market regime from a proxy's candles. Pure + testable."""
    if len(candles) < MIN_CANDLES:
        return RegimeRead(
            regime="choppy", confidence=0.4, proxy=proxy,
            trend_pct=0.0, slope_pct=0.0, annualized_vol=0.0,
            vol_ratio=1.0, drawdown_pct=0.0,
            summary="Not enough data to read the market — defaulting to choppy.",
        )

    cl = _closes(candles)
    price = cl[-1]

    ma50 = sma(cl, 50)
    sma_now = ma50[-1]
    sma_past = ma50[-11] if len(ma50) >= 11 else ma50[0]
    trend_pct = (price - sma_now) / sma_now if sma_now else 0.0
    slope_pct = (sma_now - sma_past) / sma_past if sma_past else 0.0

    rets = _returns(cl)
    recent = rets[-20:] if len(rets) >= 20 else rets
    ann_vol = _stdev(recent) * math.sqrt(252)
    base_vol = _stdev(rets) * math.sqrt(252)
    vol_ratio = (ann_vol / base_vol) if base_vol > 0 else 1.0

    peak = max(cl)
    drawdown_pct = (price - peak) / peak if peak else 0.0

    uptrend = trend_pct > TREND_BAND and slope_pct > 0
    downtrend = trend_pct < -TREND_BAND and slope_pct < 0

    if downtrend and (ann_vol >= HIGH_VOL or drawdown_pct <= RISK_OFF_DRAWDOWN):
        regime = "risk_off"
    elif downtrend:
        regime = "trending_down"
    elif ann_vol >= HIGH_VOL or vol_ratio >= VOL_SPIKE_RATIO:
        regime = "high_volatility"
    elif uptrend:
        regime = "trending_up"
    elif ann_vol <= LOW_VOL:
        regime = "low_volatility"
    else:
        regime = "choppy"

    return RegimeRead(
        regime=regime,
        confidence=round(_confidence(regime, trend_pct, slope_pct,
                                     ann_vol, vol_ratio, drawdown_pct), 2),
        proxy=proxy,
        trend_pct=round(trend_pct, 4),
        slope_pct=round(slope_pct, 4),
        annualized_vol=round(ann_vol, 4),
        vol_ratio=round(vol_ratio, 2),
        drawdown_pct=round(drawdown_pct, 4),
        summary=_summary(regime, trend_pct, ann_vol, drawdown_pct),
    )


async def read_market_regime(proxy: str = DEFAULT_PROXY) -> RegimeRead:
    """Fetch the proxy's candles and classify. Safe fallback to choppy."""
    candles: list[Candle] = []
    try:
        from app.data.candles import fetch_candles_for
        candles = await fetch_candles_for(proxy, "stock")
    except Exception:  # noqa: BLE001 — never let a data hiccup crash a tick
        candles = []
    if not candles:
        return RegimeRead(
            regime="choppy", confidence=0.4, proxy=proxy,
            trend_pct=0.0, slope_pct=0.0, annualized_vol=0.0,
            vol_ratio=1.0, drawdown_pct=0.0,
            summary="Market data unavailable — defaulting to choppy.",
        )
    return classify_regime(candles, proxy=proxy)
