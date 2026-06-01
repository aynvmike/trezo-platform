"""Position health + decayed-thesis detector.

Mike 2026-06-01: "after a trade is stalling and losing IV and TCS it
needs to pivot away and do what it needs to save the profit and go
further ahead."

This module re-scores an open position's CURRENT setup quality and
compares it to the score at entry. When the thesis has decayed - TCS
dropped meaningfully AND price action has gone flat AND the peak
gain has given back - the position is flagged with a `decayed_thesis`
signal. The Exit Advisor then surfaces an alert; user (or future
auto-rotate logic) decides whether to trim.

This is the foundation of the capital recycling work. The trade isn't
losing money - it's wasting capital that a fresher setup could earn
more on.

Decay rule (deliberately tight so we don't cry wolf):
  - Entry TCS known AND current TCS exists
  - TCS dropped >= 15% from entry (e.g. 800 -> 680)
  - Position has been open >= 2 calendar days (no whipsaw alerts)
  - Position is currently positive on P&L OR was previously positive
    (we only fire on winners we'd want to lock - not on losers
    that should hit their stop)
  - Peak giveback OR price-flat-for-2-days+ confirms the move is done

Anything that hits ALL of those gets a `rotate` recommendation. Two
out of three gets a `trim_partial` (take half off the table). Fewer
gets `hold`.

IV decay note: we don't currently snapshot entry-time IV for stock
positions. The TCS factor breakdown DOES include an iv_environment
component (when cycle awareness is on), so IV regime change shows up
in the TCS delta. When we add per-position IV snapshots, the rule
will tighten further.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import structlog

from app.data.candles import fetch_candles_for
from app.patterns.scoring import calculate_score, MarketContext

log = structlog.get_logger("trezo.position_health")


# Tuning knobs. Tightened on purpose so the bot doesn't nag.
TCS_DECAY_PCT = 0.15           # 15% TCS drop is the floor for concern
MIN_DAYS_OPEN = 2              # don't fire on intraday whipsaws
PEAK_GIVEBACK_PCT = 0.30       # 30%+ peak giveback counts as "exhausted"
FLAT_DAYS_THRESHOLD = 2        # price within +/-1% for 2+ days = stalled


@dataclass
class PositionHealth:
    """Decay snapshot for one open position."""
    ticker: str
    side: str
    entry_tcs: Optional[int]
    current_tcs: Optional[int]
    tcs_decay_pct: Optional[float]    # 0.00..1.00 (positive = TCS dropped)
    days_open: float
    flat_days: int                    # consecutive recent flat sessions
    peak_giveback_pct: Optional[float]
    is_winner: bool                   # currently in profit OR ever was
    recommendation: str               # 'rotate' | 'trim_partial' | 'hold'
    reasons: list[str]                # plain-English bullets


def _days_between(opened_at: Optional[str]) -> float:
    if not opened_at:
        return 0.0
    try:
        t = datetime.fromisoformat(opened_at.replace("Z", "+00:00"))
        return max(0.0, (datetime.now(timezone.utc) - t).total_seconds() / 86400.0)
    except Exception:  # noqa: BLE001
        return 0.0


def _flat_days(candles, window: int = 5, threshold_pct: float = 0.01) -> int:
    """How many of the last `window` sessions had close-to-close move
    less than `threshold_pct`. The bot reads price action like a
    trader: flat = thesis cooling off."""
    if not candles or len(candles) < window + 1:
        return 0
    closes = [float(c.close) for c in candles[-(window + 1):]]
    flat = 0
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        if prev <= 0:
            continue
        move = abs(closes[i] - prev) / prev
        if move < threshold_pct:
            flat += 1
    return flat


async def compute_position_health(pos: dict) -> Optional[PositionHealth]:
    """Score one open paper_position's decay state. Returns None on
    any data miss - the caller treats no-signal as 'no opinion'."""
    ticker = (pos.get("ticker") or "").upper()
    side = (pos.get("side") or "long").lower()
    asset_type = pos.get("asset_type") or "stock"
    entry = float(pos.get("entry_price") or 0)
    qty = float(pos.get("quantity") or 0)
    if not ticker or entry <= 0 or qty <= 0:
        return None

    days_open = _days_between(pos.get("entry_at"))
    if days_open < MIN_DAYS_OPEN:
        return None  # too new to call

    payload = pos.get("source_payload") or {}
    entry_tcs_raw = payload.get("tcs")
    entry_tcs = int(entry_tcs_raw) if entry_tcs_raw is not None else None
    if entry_tcs is None or entry_tcs <= 0:
        return None  # need a baseline to detect decay

    # Re-score with fresh candles.
    try:
        candles = await fetch_candles_for(ticker, asset_type)
        if not candles or len(candles) < 30:
            return None
        # MarketContext is the same shape the originating scanner used;
        # we leave catalyst_today default since we can't re-derive it
        # exactly. Decay is mostly driven by candle structure anyway.
        score = calculate_score(candles, MarketContext(),
                                strategy=payload.get("strategy"))
        current_tcs = int(score.tcs)
    except Exception as e:  # noqa: BLE001
        log.warning("position_health.rescore_failed",
                    ticker=ticker, error=str(e)[:200])
        return None

    tcs_decay_pct = max(0.0, (entry_tcs - current_tcs) / entry_tcs)

    # Peak giveback - read the running peak the Exit Advisor maintains.
    peak = float(pos.get("peak_unrealized_pnl_usd") or 0)
    spot = float(candles[-1].close)
    if side == "short":
        pnl = qty * (entry - spot)
    else:
        pnl = qty * (spot - entry)
    peak_giveback_pct: Optional[float] = None
    if peak > 0:
        peak_giveback_pct = max(0.0, (peak - pnl) / peak)

    is_winner = pnl > 0 or peak > 0
    flat = _flat_days(candles)

    # Decision rules
    reasons: list[str] = []
    if tcs_decay_pct >= TCS_DECAY_PCT:
        reasons.append(
            f"TCS decayed {tcs_decay_pct*100:.0f}% "
            f"({entry_tcs} -> {current_tcs})"
        )
    if peak_giveback_pct is not None and peak_giveback_pct >= PEAK_GIVEBACK_PCT:
        reasons.append(
            f"Peak gave back {peak_giveback_pct*100:.0f}%"
        )
    if flat >= FLAT_DAYS_THRESHOLD:
        reasons.append(f"{flat} consecutive flat sessions")

    # Recommendation tiers - all three triggers = rotate; two = trim;
    # one or zero = hold. Only winners get rotate/trim - we don't tell
    # a losing trade to rotate, that's what the stop is for.
    if not is_winner:
        recommendation = "hold"
    elif len(reasons) >= 3:
        recommendation = "rotate"
    elif len(reasons) == 2:
        recommendation = "trim_partial"
    else:
        recommendation = "hold"

    return PositionHealth(
        ticker=ticker,
        side=side,
        entry_tcs=entry_tcs,
        current_tcs=current_tcs,
        tcs_decay_pct=round(tcs_decay_pct, 4),
        days_open=round(days_open, 2),
        flat_days=flat,
        peak_giveback_pct=(round(peak_giveback_pct, 4)
                           if peak_giveback_pct is not None else None),
        is_winner=is_winner,
        recommendation=recommendation,
        reasons=reasons,
    )


def render_alert_message(h: PositionHealth) -> str:
    """Build the plain-English message the Exit Advisor banner shows."""
    if h.recommendation == "rotate":
        prefix = "Thesis exhausted"
    elif h.recommendation == "trim_partial":
        prefix = "Thesis weakening"
    else:
        prefix = "Position health"
    body = ", ".join(h.reasons) or "monitoring"
    return (
        f"{h.ticker}: {prefix}. {body}. "
        + ("Consider trimming half to free capital for higher-TCS setups."
           if h.recommendation == "trim_partial"
           else "Consider closing to free capital for higher-TCS setups."
           if h.recommendation == "rotate"
           else "No action recommended; just keeping an eye on it.")
    )
