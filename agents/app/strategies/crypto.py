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
          Holding hours-days. Target 10-15%, 5% stop, then a step-ladder
          profit lock (SWING_PROFIT_LADDER) ratchets the stop up.
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


# HODL — long-horizon accumulate-and-hold (Mike 2026-06-13). The
# thesis: hold quality names (XRP, SOL, ISO 20022 cluster) through the
# long climb, not flip them. Discipline that keeps it from becoming an
# EMOTIONAL bag-hold:
#   * Catastrophe stop only (no target, no time stop) — a HODL exits
#     ONLY if the thesis is broken by a deep drawdown.
#   * The wide stop makes the sized position SMALL (risk $ / big stop
#     distance = few coins), so a HODL can never dominate the book.
#   * Per-coin allocation cap enforced by the normal allocation gate.
# "Hold and do not sell" = the target is set so high it effectively
# never triggers; only the catastrophe stop or a manual close exits.
HODL_CATASTROPHE_STOP = 0.35   # -35%: thesis-broken line, not a trade stop
HODL_TARGET_SENTINEL = 5.0     # +500%: effectively "never auto-sell"
HODL_RSI_MAX = 25              # only accumulate when genuinely deep-value

# Trail-to-lock (crypto Part 2, 2026-06-13). Once a long HODL has run far
# enough in profit, the Position Monitor ratchets a trailing stop UP to
# lock gains -- WITHOUT ever forcing a sale at a profit target (the
# sentinel target still never triggers). "Hold, but protect a big run."
HODL_TRAIL_TRIGGER = 0.40      # +40% unrealized before trailing engages
HODL_TRAIL_GIVEBACK = 0.20     # then trail 20% below price (lock ~80% of high)

# SWING step-ladder profit lock (crypto Part 2b, 2026-06-13). A SWING is a
# DEFINED trade (it still exits at its fixed +12% target), but on the way up
# we ratchet a step-ladder stop to lock RETURN ON CAPITAL in stages, so a
# reversal before the target still banks most of the gain. Each tuple is
# (gain_trigger, locked_floor) as fractions of entry: once unrealized gain
# >= trigger, raise the stop to entry*(1+floor). Ratchets up only. The rungs
# climb toward the target, tightening the give-back as profit grows -- the
# same "tighter the more you are up" discipline as Mike's options drawback
# ladder. Tune the rungs here.
SWING_PROFIT_LADDER = (
    (0.05, 0.00),   # +5% gain  -> lock breakeven (the spec's "trail after 5%")
    (0.08, 0.03),   # +8% gain  -> lock +3%
    (0.10, 0.05),   # +10% gain -> lock +5% (target at +12% takes the rest)
)

# DCA accumulation profit lock (crypto). DCA targets are smaller (per-coin
# ~6%), so the rungs are tighter: protect capital early, lock a little after.
DCA_PROFIT_LADDER = (
    (0.03, 0.00),   # +3% gain -> lock breakeven
    (0.05, 0.02),   # +5% gain -> lock +2%
)

# Extended (STOCK multi-day swing) profit lock. Bigger moves than crypto DCA,
# so wider rungs. Kept here with the other ladders as one tunable home; the
# Position Monitor applies it to Alpaca-routed Extended rows.
EXTENDED_PROFIT_LADDER = (
    (0.04, 0.00),   # +4% gain  -> lock breakeven
    (0.07, 0.03),   # +7% gain  -> lock +3%
    (0.10, 0.06),   # +10% gain -> lock +6%
)

# Modes allowed to SCALE IN across days (accumulate on dips). One-shot
# modes (swing/scalp) still trade one position at a time. Risk Manager
# consults this to decide whether to relax its same-ticker stacking veto.
ACCUMULATION_MODES = frozenset({"hodl", "dca"})


def is_accumulation_strategy(strategy: str | None) -> bool:
    """True if a strategy tag is an accumulate-across-days crypto mode
    (crypto_hodl / crypto_dca). Tolerant of tag shape: matches
    'crypto_hodl', 'hodl', or any '*_hodl' variant."""
    s = (strategy or "").strip().lower()
    if not s:
        return False
    for m in ACCUMULATION_MODES:
        if s == m or s == f"crypto_{m}" or s.endswith(f"_{m}"):
            return True
    return False


def get_crypto_universe(user_id=None) -> list[str]:
    """Task #50 (2026-06-05): expandable crypto universe.

    Seed = CRYPTO_WATCHLIST (curated by spec) union any tickers in
    user watchlists with asset_type='crypto'. Falls back to the static
    seed on DB error. Mike's rule: watchlist is personalization, not
    cap; the bot should consider any crypto Mike adds.
    """
    try:
        from app.runtime.persistence import _client
        client = _client()
        if not client:
            return list(CRYPTO_WATCHLIST)
        q = client.table("watchlist_tickers").select("ticker").eq("asset_type", "crypto")
        if user_id:
            q = q.eq("user_id", user_id)
        res = q.execute()
        extras = []
        for row in (res.data or []):
            t = (row.get("ticker") or "").strip().upper()
            if t and t not in extras:
                extras.append(t)
        seed = list(CRYPTO_WATCHLIST)
        for e in extras:
            if e not in seed:
                seed.append(e)
        return seed
    except Exception:  # noqa: BLE001
        return list(CRYPTO_WATCHLIST)


@dataclass
class CryptoSignal:
    ticker: str
    mode: str            # 'scalp' | 'swing' | 'dca' | 'hodl'
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

    Mode priority: SWING (strongest) > HODL (deepest value, RSI<25) >
    DCA (oversold, RSI<35) > SCALP (default).
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

    # --- HODL: long-horizon accumulate-and-hold. Deepest value tier. ---
    # Fires only when genuinely deep-value (RSI < 25). Catastrophe stop,
    # sentinel target (hold, don't sell), small size by construction.
    if rsi_now < HODL_RSI_MAX:
        return CryptoSignal(
            ticker=sym, mode="hodl", direction="bullish",
            stop_pct=HODL_CATASTROPHE_STOP, target_pct=HODL_TARGET_SENTINEL,
            rsi=rsi_now, bb_width_pct=bb_w, volume_ratio=vol_ratio,
            reason=(f"HODL - RSI {rsi_now:.0f} deep-value; long-horizon "
                    f"accumulate, catastrophe stop -{int(HODL_CATASTROPHE_STOP*100)}%, "
                    f"hold (no profit target)."),
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
