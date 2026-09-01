"""Opening Range Breakout (ORB) - Section 6 of TREZO_NOVA_BOT_TRADE_RULES.

The opening range is the high/low of the first five 1-minute bars of the
regular session (9:30-9:35 AM ET). A confirmed breakout is two completed
1-minute bars closing on the same side of that range. Quality gates: the
opening range must be a sane size versus the daily ATR, and the breakout
bar should trade above the opening range's average volume.

Auto-trade windows:
  - best     : 9:35-10:30 AM ET
  - reduced  : 10:30-11:30 AM ET (smaller size)
  - none     : after 11:30 AM ET

Section 7 (ORB options credit spreads) is a separate follow-on - it needs
credit-spread and iron-condor modeling Trezo does not have yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from app.strategies.market_filter import atr

# Liquid names suited to ORB day-trading.
ORB_WATCHLIST = ["SPY", "QQQ", "AAPL", "NVDA", "AMD", "TSLA", "MSFT", "META"]

OPENING_RANGE_BARS = 5          # first five 1-minute bars = the 9:30-9:35 range
CONFIRM_BARS = 2                # 1-minute closes outside the range to confirm
ORB_MIN_ATR_RATIO = 0.10        # opening range must be >= 10% of daily ATR
ORB_MAX_ATR_RATIO = 0.80        # ... and <= 80% (else the move may be exhausted)

# ORB auto-trade windows, in UTC minutes-of-day (ET is UTC-4 in DST).
# Mike's request 2026-05-28: extend the window — start at 8:30 AM ET to
# catch the pre-market opening range, end at 12:00 PM ET to give the bot
# more daylight to confirm continuations. Best/reduced split keeps the
# largest size in the strongest hour after the regular open.
_BEST_START = 12 * 60 + 30      # 8:30 AM ET — pre-market opening range
_REDUCED_START = 14 * 60 + 30   # 10:30 AM ET — reduced sizing
_WINDOW_END = 16 * 60           # 12:00 PM ET — window closes


def orb_window() -> tuple[bool, str]:
    """Return (within_window, sub_window). sub_window is 'best' | 'reduced' | ''."""
    now = datetime.now(timezone.utc)
    mod = now.hour * 60 + now.minute
    if _BEST_START <= mod < _REDUCED_START:
        return True, "best"
    if _REDUCED_START <= mod < _WINDOW_END:
        return True, "reduced"
    return False, ""


@dataclass
class ORBSignal:
    symbol: str
    direction: str          # 'bullish' | 'bearish'
    range_high: float
    range_low: float
    breakout_price: float
    atr_ratio: float        # opening range height / daily ATR
    volume_ok: bool
    sub_window: str
    stop_pct: float
    target_pct: float
    tcs: int                # 0-100 scale (EQ-5)


def evaluate_orb(symbol: str, candles_1m, daily_atr: float,
                 sub_window: str) -> Optional[ORBSignal]:
    """Detect a confirmed opening-range breakout from today's 1-minute bars."""
    if not candles_1m or len(candles_1m) < OPENING_RANGE_BARS + CONFIRM_BARS:
        return None

    opening = candles_1m[:OPENING_RANGE_BARS]
    range_high = max(float(c.high) for c in opening)
    range_low = min(float(c.low) for c in opening)
    range_height = range_high - range_low
    if range_height <= 0:
        return None

    # Range-quality gate versus the daily ATR.
    atr_ratio = (range_height / daily_atr) if daily_atr > 0 else 0.0
    if daily_atr > 0 and not (ORB_MIN_ATR_RATIO <= atr_ratio <= ORB_MAX_ATR_RATIO):
        return None

    opening_avg_vol = sum(float(c.volume) for c in opening) / OPENING_RANGE_BARS

    # Find the first 2-in-a-row confirmed breakout, same side.
    after = candles_1m[OPENING_RANGE_BARS:]
    direction = ""
    breakout_price = 0.0
    confirm_bar = None
    for i in range(len(after) - CONFIRM_BARS + 1):
        window = after[i:i + CONFIRM_BARS]
        closes = [float(c.close) for c in window]
        if all(c > range_high for c in closes):
            direction, breakout_price, confirm_bar = "bullish", closes[-1], window[-1]
            break
        if all(c < range_low for c in closes):
            direction, breakout_price, confirm_bar = "bearish", closes[-1], window[-1]
            break
    if not direction or confirm_bar is None:
        return None

    volume_ok = float(confirm_bar.volume) >= opening_avg_vol

    # Stop at the far side of the opening range; target at 2R.
    if direction == "bullish":
        stop_dist = breakout_price - range_low
    else:
        stop_dist = range_high - breakout_price
    if stop_dist <= 0 or breakout_price <= 0:
        return None
    stop_pct = stop_dist / breakout_price
    target_pct = stop_pct * 2.0

    # ORB confidence: a confirmed breakout starts at 72; quality adds to it.
    # EQ-5: TCS is 0-100 platform-wide since 2026-07-08. This hand-built
    # score stayed on the old 0-1000 scale (720/60/40/40, cap 900), so ORB
    # signals sailed over every per-book floor and carried confidence > 1.
    # Same components divided by 10; the shape of the score is unchanged.
    tcs = 72
    if volume_ok:
        tcs += 6
    if sub_window == "best":
        tcs += 4
    if 0.20 <= atr_ratio <= 0.55:
        tcs += 4
    tcs = min(tcs, 90)

    return ORBSignal(
        symbol=symbol.upper(), direction=direction,
        range_high=round(range_high, 4), range_low=round(range_low, 4),
        breakout_price=round(breakout_price, 4),
        atr_ratio=round(atr_ratio, 2), volume_ok=volume_ok,
        sub_window=sub_window,
        stop_pct=round(stop_pct, 4), target_pct=round(target_pct, 4),
        tcs=tcs,
    )
