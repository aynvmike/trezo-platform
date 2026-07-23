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
    # 2026-07-13 (Mike): liquid majors added so the crypto desk sees more
    # of the market -- volatility-scaled stops/targets, fee gate applies.
    "DOGE": {"stop_pct": 0.05,  "target_pct": 0.09},
    "LTC":  {"stop_pct": 0.035, "target_pct": 0.07},
    "LINK": {"stop_pct": 0.04,  "target_pct": 0.08},
    "DOT":  {"stop_pct": 0.04,  "target_pct": 0.08},
    "AVAX": {"stop_pct": 0.045, "target_pct": 0.09},
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
CRYPTO_WATCHLIST: list[str] = (["BTC", "ETH", "SOL", "DOGE", "LTC", "LINK", "DOT", "AVAX"]
                               + ISO20022_SYMBOLS)  # majors widened 2026-07-13
# BTC added 2026-07-23 (Mike: "from bitcoin to XRP") -- it had COIN_PARAMS
# from day one but was never put on the scan list.


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


# ---- Fee-aware net-edge gate (Mike 2026-06-15) -----------------------------
# Take a crypto trade whenever the expected move clears round-trip trading
# cost (fee + slippage on BOTH the entry and the exit) PLUS a small net
# cushion. NEVER gate crypto on the coin's price or absolute cost -- only on
# whether the trade can net a profit after costs. Fee/slippage are modeled in
# paper/engine.py; helpers take them as params so callers pass live values and
# there's one source of truth. bps = basis points (1 bp = 0.01%).
MIN_NET_EDGE_PCT = 0.0001  # +0.01% net cushion required ON TOP of round-trip cost


def round_trip_cost_pct(fee_bps: float, slippage_bps: float) -> float:
    """Round-trip trading cost as a fraction of notional: fee + slippage
    charged on BOTH the entry fill and the exit fill."""
    return 2.0 * (float(fee_bps) + float(slippage_bps)) / 10_000.0


def net_edge_pct(target_pct: float, fee_bps: float, slippage_bps: float) -> float:
    """Expected NET edge as a fraction: gross target move minus round-trip
    cost. Positive => profitable after costs."""
    return float(target_pct) - round_trip_cost_pct(fee_bps, slippage_bps)


def clears_fee_edge(target_pct: float, fee_bps: float, slippage_bps: float,
                    buffer: float = MIN_NET_EDGE_PCT) -> bool:
    """The gate: True when expected net edge meets the required cushion
    (default +0.01%). Independent of the coin's price/cost."""
    return net_edge_pct(target_pct, fee_bps, slippage_bps) >= float(buffer)


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


# --- Mode tuning (crypto Part 4, 2026-06-13) -------------------------------
# Tuned for ACTIVITY and per Mike's strategy character:
#   SCALP = fast, loose, FLEXIBLE quick trade; volume-OPTIONAL so it still
#           fires when a coin's feed reports no volume (the old SCALP needed a
#           volume surge and was mathematically DEAD on no-volume feeds -- the
#           #1 reason crypto sat silent for hours).
#   DCA   = oversold accumulation, a touch looser to catch more dips.
#   SWING = trend expansion, slightly looser bands.
#   HODL  = stays TIGHT + selective -- deepest value only (RSI < HODL_RSI_MAX),
#           hold and never chase; the catastrophe stop is the only exit.
# All edges live here so they are easy to retune in one place.
# Mode thresholds -- env-tunable + RECALIBRATED 2026-07-02. The old
# SCALP_BB_MAX=2.2 was calibrated for a different BB scale: real daily
# bb_width_pct readings run 17-36%, so SCALP could mathematically NEVER
# fire, and SWING's 1.1x volume-expansion demand kept the whole crypto
# pocket idle through quiet weeks (activity-log evidence 7/2: ETH/SOL/XRP
# all "no_setup" on vol 0.2-0.6x). Entries remain gated by TCS floor +
# net-edge (fees+slippage) + per-coin cap + the allocation pocket.
import os as _os


def _envf(name: str, default: float) -> float:
    try:
        return float(_os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


SCALP_RSI_LO, SCALP_RSI_HI = 40, 68
SCALP_BB_MAX = _envf("TREZO_CRYPTO_SCALP_BB_MAX", 25.0)
SCALP_VOL_MIN = _envf("TREZO_CRYPTO_SCALP_VOL_MIN", 0.4)
SWING_RSI_LO, SWING_RSI_HI = 48, 72
SWING_BB_MIN = _envf("TREZO_CRYPTO_SWING_BB_MIN", 2.0)
SWING_VOL_MIN = _envf("TREZO_CRYPTO_SWING_VOL_MIN", 0.8)
DCA_RSI_MAX = _envf("TREZO_CRYPTO_DCA_RSI_MAX", 40)


def _vol_ratio_live(candles: list[Candle]) -> tuple[float, float]:
    """Last-bar volume ratio, PRO-RATED for the still-filling candle.

    Mike 2026-07-23 ("no crypto trades in days... even while the market
    is open around this hour"): the last candle is PARTIAL -- in the
    early hours it holds only a fraction of its period's volume, so the
    old last/avg read chronically scored overnight tape as dead (0.07-
    0.27 at 3 AM vs 0.5+ mid-morning) and quietly benched a 24/7 lane
    every night. Compare instead against what the AVERAGE candle would
    have accumulated by the same elapsed fraction of its period.
    Granularity-agnostic (Kraken 4h bars or CoinGecko daily). Falls
    back to the raw ratio if timestamps are unusable."""
    last_vol = candles[-1].volume
    avg_vol = avg_volume(candles[:-1], 20)
    if avg_vol <= 0:
        return 0.0, avg_vol
    frac = 1.0
    try:
        from datetime import datetime as _dtv, timezone as _tzv
        if len(candles) >= 3:
            period = (candles[-1].timestamp - candles[-2].timestamp).total_seconds()
            if period > 0:
                elapsed = (_dtv.now(_tzv.utc) - candles[-1].timestamp).total_seconds()
                frac = max(0.08, min(elapsed / period, 1.0))
    except Exception:  # noqa: BLE001
        frac = 1.0
    return (last_vol / (avg_vol * frac)), avg_vol


def indicators(candles: list[Candle]) -> dict:
    """The raw read each mode is judged on -- RSI, Bollinger width %, last-bar
    volume ratio -- so the scanner can SHOW why a coin did or did not fire."""
    if len(candles) < 25:
        return {"insufficient": True, "bars": len(candles)}
    cl = closes(candles)
    rsi_now = rsi(cl, 14)[-1]
    bb_w = _bb_width_pct(cl)
    vol_ratio, avg_vol = _vol_ratio_live(candles)
    return {
        "rsi": round(rsi_now, 1),
        "bb_width_pct": round(bb_w, 2),
        "vol_ratio": round(vol_ratio, 2),
        "has_volume": avg_vol > 0,
    }


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

    vol_ratio, avg_vol = _vol_ratio_live(candles)

    base = COIN_PARAMS[sym]

    # Volume is OPTIONAL when the feed reports none (avg_vol == 0): a coin
    # without volume data should still trade on price/RSI/range, not be frozen
    # out. This is what revives SCALP/SWING on no-volume feeds.
    has_vol = avg_vol > 0

    # --- SWING: trend expansion. Wide bands + healthy RSI. ---
    if (bb_w > SWING_BB_MIN and SWING_RSI_LO <= rsi_now <= SWING_RSI_HI
            and (vol_ratio >= SWING_VOL_MIN or not has_vol)):
        return CryptoSignal(
            ticker=sym, mode="swing", direction="bullish",
            stop_pct=0.05, target_pct=0.12,   # swing geometry overrides per-coin
            rsi=rsi_now, bb_width_pct=bb_w, volume_ratio=vol_ratio,
            reason=f"SWING — BB width {bb_w:.1f}% > {SWING_BB_MIN}, RSI {rsi_now:.0f}",
        )

    # --- HODL: deep-value hold. TIGHT + selective by design (Mike): only the
    # deepest value (RSI < HODL_RSI_MAX) triggers; the catastrophe stop is the
    # only exit (hold, never chase). Kept strict on purpose. ---
    if rsi_now < HODL_RSI_MAX:
        return CryptoSignal(
            ticker=sym, mode="hodl", direction="bullish",
            stop_pct=HODL_CATASTROPHE_STOP, target_pct=HODL_TARGET_SENTINEL,
            rsi=rsi_now, bb_width_pct=bb_w, volume_ratio=vol_ratio,
            reason=(f"HODL - RSI {rsi_now:.0f} deep-value; long-horizon "
                    f"accumulate, catastrophe stop -{int(HODL_CATASTROPHE_STOP*100)}%, "
                    f"hold (no profit target)."),
        )

    # --- DCA: oversold accumulation. ---
    if rsi_now < DCA_RSI_MAX:
        return CryptoSignal(
            ticker=sym, mode="dca", direction="bullish",
            stop_pct=base["stop_pct"], target_pct=base["target_pct"],
            rsi=rsi_now, bb_width_pct=bb_w, volume_ratio=vol_ratio,
            reason=f"DCA - RSI {rsi_now:.0f} oversold, accumulating.",
        )

    # --- SCALP: fast, flexible default for calm/range coins. Loose bands,
    # volume-OPTIONAL so it is not frozen out on no-volume feeds. ---
    if (bb_w < SCALP_BB_MAX and SCALP_RSI_LO <= rsi_now <= SCALP_RSI_HI
            and (vol_ratio >= SCALP_VOL_MIN or not has_vol)):
        return CryptoSignal(
            ticker=sym, mode="scalp", direction="bullish",
            stop_pct=max(base["stop_pct"] * 0.6, 0.01),
            target_pct=max(base["target_pct"] * 0.5, 0.02),
            rsi=rsi_now, bb_width_pct=bb_w, volume_ratio=vol_ratio,
            reason=f"SCALP - BB {bb_w:.1f}% range, RSI {rsi_now:.0f}, vol {vol_ratio:.1f}x.",
        )

    return None
