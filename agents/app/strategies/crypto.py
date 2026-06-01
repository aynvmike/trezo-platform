"""Crypto bot strategy — SCALP / SWING / DCA adaptive modes.

Spec (TREZO_STRATEGY_RULES.md §2):

Coins traded (per-coin stop/target):
  XRP — stop 3%,   target 6%
  ETH — stop 2.5%, target 5%
  SOL — stop 4%,   target 8%

Three adaptive modes:
  SCALP — RSI 40-68, normal volatility, volume >= 1.2x avg.
          Holding 1-6 candles. Target ~3%, tight stop.
  SWING — strong trend + volume + Bollinger width > 2.5%.
          Holding hours-days. Target 10-15%, 5% stop, trail after 5%.
  DCA   — RSI < 35 (accumulate). Slow buying back toward the mean.

Runs 24/7 — crypto has no market-hours window.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.patterns import Candle
from app.patterns.indicators import rsi, bollinger, closes, avg_volume


# ---- Per-coin configuration ------------------------------------------------

# Core layer-1 names trading-tuned over many sessions. The ISO 20022
# cluster underneath gets its stops/targets derived from liquidity
# tier so we don't have to hand-tune each one. See
# `app.data.iso20022_coins.default_params_for`.
from app.data.iso20022_coins import (
    ISO20022_SYMBOLS, default_params_for,
)

COIN_PARAMS: dict[str, dict[str, float]] = {
    # Hand-tuned majors
    "ETH": {"stop_pct": 0.025, "target_pct": 0.05},
    "SOL": {"stop_pct": 0.04,  "target_pct": 0.08},
    "BTC": {"stop_pct": 0.025, "target_pct": 0.05},
}
# Layer the ISO 20022-aligned cluster on top, tier-defaulted.
for _sym in ISO20022_SYMBOLS:
    _p = default_params_for(_sym)
    if _p is not None and _sym not in COIN_PARAMS:
        COIN_PARAMS[_sym] = _p

# Default scanning universe. Hand-curated majors first, then the
# ISO 20022-aligned cluster. Mike's per-stock strategy preference
# applies - the scanner can flip strategy per coin without flipping
# the whole universe.
CRYPTO_WATCHLIST: list[str] = ["ETH", "SOL"] + ISO20022_SYMBOLS


@dataclass
class CryptoSignal:
    ticker: str
    mode: str            # 'scalp' | 'swing' | 'dca'
    direction: str       # 'bullish' (long) — Phase 6c is long-only for crypto
    stop_pct: float
    target_pct: float
    rsi: float
    bb_width_pct: float
    volume_ratio: float
    reason: str


def _bb_width_pct(values: list[float]) -> float:
    """Bollinger band width as a % of the mid band."""
    bb = bollinger(values, 20, 2.0)
    if not bb["mid"] or bb["mid"][-1] == 0:
        return 0.0
    width = bb["upper"][-1] - bb["lower"][-1]
    return width / bb["mid"][-1] * 100.0


def detect_mode(ticker: str, candles: list[Candle]) -> Optional[CryptoSignal]:
    """Evaluate a coin and return a CryptoSignal if a mode triggers, else None.

    Mode priority: SWING (strongest) > DCA (deep value) > SCALP (default).
    Long-only for Phase 6c — short crypto comes later.
    """
    sym = ticker.upper()
    if sym not in COIN_PARAMS:
        return None
    if len(candles) < 25:
        return None

    cl = closes(candles)
    rsi_now = rsi(cl, 14)[-1]
    bb_w = _bb_width_pct(cl)

    last_vol = candles[-1].volume
    avg_vol = avg_volume(candles[:-1], 20)
    vol_ratio = (last_vol / avg_vol) if avg_vol > 0 else 0.0

    base = COIN_PARAMS[sym]

    # --- SWING: strong expansion. Wide bands + healthy RSI + volume. ---
    if bb_w > 2.5 and 50 <= rsi_now <= 70 and (vol_ratio >= 1.2 or avg_vol == 0):
        return CryptoSignal(
            ticker=sym, mode="swing", direction="bullish",
            stop_pct=0.05, target_pct=0.12,   # swing geometry overrides per-coin
            rsi=rsi_now, bb_width_pct=bb_w, volume_ratio=vol_ratio,
            reason=f"SWING — BB width {bb_w:.1f}% > 2.5, RSI {rsi_now:.0f}",
        )

    # --- DCA: deep value accumulation. RSI oversold. ---
    if rsi_now < 35:
        return CryptoSignal(
            ticker=sym, mode="dca", direction="bullish",
            stop_pct=base["stop_pct"], target_pct=base["target_pct"],
            rsi=rsi_now, bb_width_pct=bb_w, volume_ratio=vol_ratio,
            reason=f"DCA - RSI {rsi_now:.0f} oversold, accumulating.",
        )

    # --- SCALP: tight range + volume pop. ---
    if bb_w < 1.5 and vol_ratio >= 1.5 and 45 <= rsi_now <= 60:
        return CryptoSignal(
            ticker=sym, mode="scalp", direction="bullish",
            stop_pct=max(base["stop_pct"] * 0.6, 0.01),
            target_pct=max(base["target_pct"] * 0.5, 0.02),
            rsi=rsi_now, bb_width_pct=bb_w, volume_ratio=vol_ratio,
            reason=f"SCALP - BB width {bb_w:.1f}% tight, volume {vol_ratio:.1f}x.",
        )

    return None
