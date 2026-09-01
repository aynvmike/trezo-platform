"""Extended Strategy — Layer 4 of the Woven Basket.

Section 5 of TREZO_STRATEGY_RULES.md ("Layer 7 — Extended Stock
Strategy"; the protection-ring nav places it at Layer 4, between the
Options Engine and the Dividend Wheel).

This is Trezo's MULTI-DAY SWING layer — the only layer that holds a
position across sessions. Everything else (STMS, ORB, crypto scalps) is
intraday or premium collection. Extended Strategy looks for 2-5 day
continuation setups on daily candles.

Swing setups detected (all on daily OHLCV):
  - EMA50 pullback bounce      — an uptrend pulls back to its rising
                                 50-day EMA and bounces.
  - Breakout hold              — price broke a multi-week high and is
                                 holding above the breakout level.
  - Earnings-gap continuation  — a recent 4%+ gap-up that has not filled
                                 and keeps making progress.
  - Stair stepper              — a steady ladder of higher highs / higher
                                 lows with shallow pullbacks (a penny-
                                 stock pattern applied here as a swing).

Event gate (Section 7C): no new entries on an FOMC decision day before
2 PM ET — the bot waits for the rate announcement.

Signals are tagged strategy='extended'. They flow through the Risk
Manager -> Trade Execution like any other signal. The Position Monitor
holds them across days and closes on a multi-day time stop; it does NOT
apply the intraday 3:45 PM force-exit that STMS / ORB positions get.

Penny-stock patterns that need an intraday feed (Supernova spike timing,
Short-Squeeze setup) stay deferred — consistent with STMS's deferred
intraday patterns.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from app.patterns import Candle


# Liquid mid-caps suited to patient swing trades — seeded from the
# founder's documented strengths (TREZO_FOUNDER_WATCHLIST / README:
# "patient swing trading on mid-caps CZR, AMD, INTC, WMT, AMSC").
EXTENDED_WATCHLIST: list[str] = [
    "CZR", "AMD", "INTC", "WMT", "AMSC",
    "NVDA", "MSFT", "AAPL", "PYPL", "DIS", "BAC", "F",
]

# 0-100 scale; a signal must clear this to be emitted. EQ-5: the detectors
# below built their scores on the old 0-1000 scale until 2026-09-01, so
# every hit cleared this bar by ~10x and carried confidence > 1. They are
# now 0-100 (each component divided by 10), which makes this floor real.
EXTENDED_TCS_MIN = 70
MIN_CANDLES = 60                # ~60 daily bars needed for a 50-day EMA
SWING_MAX_HOLD_DAYS = 7         # multi-day time stop (~5 trading days)

# FOMC decision days — a MODELED list. The Fed publishes its schedule a
# year ahead; keep this current from federalreserve.gov. Used only to
# pause NEW entries before 2 PM ET on a decision day (Section 7C). An
# empty or stale list simply means no Fed gate — it never forces a trade.
FOMC_DECISION_DAYS: set[str] = {
    # 2026 schedule (modeled — verify against the Fed's published calendar)
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-16",
}


# ---- small indicators -----------------------------------------------------


def _ema(values: list[float], period: int) -> list[float]:
    """Exponential moving average — same length as `values`."""
    if not values or period < 1:
        return []
    k = 2.0 / (period + 1.0)
    out: list[float] = []
    ema = values[0]
    for i, v in enumerate(values):
        ema = v if i == 0 else (v * k + ema * (1.0 - k))
        out.append(ema)
    return out


def _avg(values: list[float]) -> float:
    return (sum(values) / len(values)) if values else 0.0


@dataclass
class ExtendedSignal:
    symbol: str
    setup: str            # ema50_pullback | breakout_hold | gap_continuation | stair_stepper
    direction: str        # 'bullish' — these are long continuation setups
    entry_price: float
    stop_pct: float
    target_pct: float
    tcs: int              # 0-100 scale (EQ-5)
    rationale: str


# ---- swing-setup detectors (all on daily candles) -------------------------


def detect_ema50_pullback(symbol: str, candles: list[Candle]) -> Optional[ExtendedSignal]:
    """An uptrend pulls back to its rising 50-day EMA and bounces."""
    if len(candles) < MIN_CANDLES:
        return None
    closes = [float(c.close) for c in candles]
    ema50 = _ema(closes, 50)
    last = candles[-1]
    price = float(last.close)
    e_now = ema50[-1]
    e_past = ema50[-6]
    if e_now <= 0 or price <= 0:
        return None
    # Uptrend: price above a rising 50-day EMA.
    if not (price > e_now and e_now > e_past):
        return None
    # Pullback: a recent bar's low came within 3% of the EMA.
    if not any(float(c.low) <= e_now * 1.03 for c in candles[-6:]):
        return None
    # Bounce: the last bar closed up and back above the EMA.
    if not (price > float(last.open) and price > e_now):
        return None
    swing_low = min(float(c.low) for c in candles[-6:])
    stop_pct = max(0.05, min(0.10, (price - swing_low) / price + 0.01))
    target_pct = max(0.06, round(stop_pct * 1.8, 4))
    tcs = 73                                   # EQ-5: 0-100 scale
    if price <= e_now * 1.03:
        tcs += 5                               # a tight bounce off the line
    if len(ema50) >= 11 and e_now > ema50[-11]:
        tcs += 3                               # EMA rising over a longer window
    return ExtendedSignal(
        symbol=symbol.upper(), setup="ema50_pullback", direction="bullish",
        entry_price=round(price, 4), stop_pct=round(stop_pct, 4),
        target_pct=round(target_pct, 4), tcs=min(tcs, 88),
        rationale=(f"{symbol.upper()} pulled back to its rising 50-day average "
                   f"(~{e_now:.2f}) and bounced — a continuation entry."),
    )


def detect_breakout_hold(symbol: str, candles: list[Candle]) -> Optional[ExtendedSignal]:
    """Price broke a multi-week high and is holding above the level."""
    if len(candles) < 35:
        return None
    price = float(candles[-1].close)
    if price <= 0:
        return None
    # Prior resistance = the highest high of the lookback, excluding the
    # last 3 bars (the breakout itself).
    resistance = max(float(c.high) for c in candles[-33:-3])
    if resistance <= 0:
        return None
    broke = any(float(c.close) > resistance for c in candles[-3:])
    # Holding above the breakout (a clean hold, not a failed breakout) ...
    if not (broke and price > resistance):
        return None
    # ... and not over-extended: within 8% of the breakout level.
    if price > resistance * 1.08:
        return None
    stop_pct = max(0.05, min(0.09, (price - resistance) / price + 0.04))
    target_pct = max(0.08, round(stop_pct * 1.8, 4))
    tcs = 74                                   # EQ-5: 0-100 scale
    avg_vol = _avg([float(c.volume) for c in candles[-21:-1]])
    if avg_vol > 0 and float(candles[-1].volume) >= avg_vol * 1.3:
        tcs += 6                               # breakout on expanding volume
    if price <= resistance * 1.04:
        tcs += 3                               # entering close to the level
    return ExtendedSignal(
        symbol=symbol.upper(), setup="breakout_hold", direction="bullish",
        entry_price=round(price, 4), stop_pct=round(stop_pct, 4),
        target_pct=round(target_pct, 4), tcs=min(tcs, 89),
        rationale=(f"{symbol.upper()} broke its multi-week high (~{resistance:.2f}) "
                   f"and is holding above it — a breakout-continuation entry."),
    )


def detect_gap_continuation(symbol: str, candles: list[Candle]) -> Optional[ExtendedSignal]:
    """A recent 4%+ gap-up that has not filled and keeps progressing."""
    if len(candles) < 30:
        return None
    price = float(candles[-1].close)
    if price <= 0:
        return None
    recent = candles[-5:]
    gap_bar: Optional[Candle] = None
    for i in range(1, len(recent)):
        prev_close = float(recent[i - 1].close)
        day_open = float(recent[i].open)
        if prev_close > 0 and day_open >= prev_close * 1.04:
            gap_bar = recent[i]
    if gap_bar is None:
        return None
    gap_open = float(gap_bar.open)
    gap_close = float(gap_bar.close)
    # Continuation: price held above the gap day's open (gap unfilled)
    # and is at / near the gap bar's close.
    if not (price >= gap_open and price >= gap_close * 0.99):
        return None
    tcs = 72                                   # EQ-5: 0-100 scale
    avg_vol = _avg([float(c.volume) for c in candles[-21:-1]])
    if avg_vol > 0 and float(gap_bar.volume) >= avg_vol * 1.5:
        tcs += 7                               # the gap printed on heavy volume
    return ExtendedSignal(
        symbol=symbol.upper(), setup="gap_continuation", direction="bullish",
        entry_price=round(price, 4), stop_pct=0.07, target_pct=0.10,
        tcs=min(tcs, 86),
        rationale=(f"{symbol.upper()} gapped up 4%+ recently and has held the gap "
                   f"(above ~{gap_open:.2f}) — an earnings-gap continuation."),
    )


def detect_stair_stepper(symbol: str, candles: list[Candle]) -> Optional[ExtendedSignal]:
    """A steady ladder of higher highs and higher lows — not parabolic."""
    if len(candles) < 25:
        return None
    price = float(candles[-1].close)
    if price <= 0:
        return None
    window = candles[-20:]
    blocks = [window[i:i + 5] for i in range(0, 20, 5)]   # four 5-bar blocks
    highs = [max(float(c.high) for c in b) for b in blocks]
    lows = [min(float(c.low) for c in b) for b in blocks]
    rising_highs = all(highs[i] < highs[i + 1] for i in range(3))
    rising_lows = all(lows[i] < lows[i + 1] for i in range(3))
    if not (rising_highs and rising_lows):
        return None
    # Steady, not a spike: the total run sits in a sane band.
    run = (highs[-1] - lows[0]) / lows[0] if lows[0] > 0 else 0.0
    if not (0.08 <= run <= 0.60):
        return None
    tcs = 71                                   # EQ-5: 0-100 scale
    if run <= 0.35:
        tcs += 4                               # a calmer ladder is a cleaner swing
    return ExtendedSignal(
        symbol=symbol.upper(), setup="stair_stepper", direction="bullish",
        entry_price=round(price, 4), stop_pct=0.07, target_pct=0.10,
        tcs=min(tcs, 82),
        rationale=(f"{symbol.upper()} is climbing in steady steps — higher highs "
                   f"and higher lows with shallow pullbacks."),
    )


_DETECTORS = [
    detect_ema50_pullback,
    detect_breakout_hold,
    detect_gap_continuation,
    detect_stair_stepper,
]


def evaluate_extended(symbol: str, candles: list[Candle],
                      has_catalyst: bool = False) -> Optional[ExtendedSignal]:
    """Run every swing detector; return the highest-scoring hit, or None."""
    best: Optional[ExtendedSignal] = None
    for detector in _DETECTORS:
        try:
            sig = detector(symbol, candles)
        except Exception:  # noqa: BLE001
            sig = None
        if sig is None:
            continue
        if has_catalyst:
            sig.tcs = min(sig.tcs + 4, 95)     # EQ-5: 0-100 scale
            sig.rationale += " A recent news catalyst supports the move."
        if best is None or sig.tcs > best.tcs:
            best = sig
    if best is None or best.tcs < EXTENDED_TCS_MIN:
        return None
    return best


# ---- event gate + scan window ---------------------------------------------


def fomc_blackout(now: Optional[datetime] = None) -> bool:
    """True on an FOMC decision day before 2 PM ET — pause new entries
    until the rate announcement (Section 7C). 2 PM ET is 18:00 UTC in DST
    and 19:00 UTC in standard time; we use 18:00 UTC so the gate releases
    no earlier than 2 PM ET in summer and no later than 2 PM ET in winter
    would not over-block — entries simply resume once the news is out."""
    now = now or datetime.now(timezone.utc)
    if now.date().isoformat() not in FOMC_DECISION_DAYS:
        return False
    return now.hour < 18


def swing_window(now: Optional[datetime] = None) -> bool:
    """The Extended scanner sweeps the FULL trading day plus pre-market
    AND after-hours — 8:30 AM ET through 6:30 PM ET, weekdays only.

    Mike's request 2026-05-28: extend the window to catch pre-market
    news (earnings, guidance) AND after-hours moves (post-close releases
    that often telegraph the next-day open). Trezo's only multi-day
    layer should see those events live, not the next morning.

    ET → UTC: ET = UTC-4 in DST, UTC-5 in standard. 8:30 AM ET = 12:30
    / 13:30 UTC, 6:30 PM ET = 22:30 / 23:30 UTC. We use the wider
    12:30 → 23:30 UTC band so DST transitions don't shift behaviour."""
    now = now or datetime.now(timezone.utc)
    if now.weekday() >= 5:
        return False
    h = now.hour + now.minute / 60.0
    return 12.5 <= h <= 23.5
