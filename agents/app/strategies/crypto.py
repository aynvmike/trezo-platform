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


def ensure_coin_params(symbol: str, tier: str = "c") -> None:
    """Runtime params for DISCOVERED coins (expander, 2026-07-23) --
    tier defaults from the ISO registry so thin names get wide stops."""
    try:
        from app.data.iso20022_coins import TIER_DEFAULT_PARAMS
        sym = (symbol or "").upper().strip()
        if sym and sym not in COIN_PARAMS:
            COIN_PARAMS[sym] = dict(
                TIER_DEFAULT_PARAMS.get(tier, TIER_DEFAULT_PARAMS["c"]))
    except Exception:  # noqa: BLE001
        pass

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
# RUNG REPLAY, 2026-08-19 (Mike). The rungs above were measured against 30
# days of real closed crypto longs (90 trades, $112k notional). Result: they
# armed on SIX of ninety trades and moved the month's P&L by $1.68. Sixty of
# ninety trades never reached even +0.8%, and the median scalp/DCA peak is
# ~0.58% -- BELOW the 0.62% round-trip cost. A ladder whose first rung is
# +5% is not protection on this book; it is decoration.
#
# The replay says nearly all the value is in the FIRST rung: a +0.8% trigger
# fired on 38 of 90 and added $306 over the month, while the +5% rung fired
# on 6 and added $119. Same trades, retuned ladder: -$456.87 actual becomes
# -$47.74 modelled.
#
# WHY THE GAP BETWEEN TRIGGER AND LOCK MATTERS MORE THAN THE TRIGGER: the
# replay knows entry, peak and final exit -- NOT the path between them, so
# it cannot see a stop tripped early by a wiggle. A 0.65%/0.63% pair scored
# best in the model and is the worst real choice: 0.02% of room, and $672 of
# realized profit standing behind it. Mike chose the +0.8% and +1.0% rows,
# which arm early and then widen the room to 0.35% as the trade proves out.
#
# EVERY LOCK HERE MUST CLEAR round_trip_cost_pct() = 0.62%. A lock under it
# books a LOSS while the log says "profit locked" -- see ladder_clears_fees().
SWING_PROFIT_LADDER = (
    (0.008, 0.0065),  # +0.8% peak -> lock +0.65% (just over the 0.62% floor)
    (0.010, 0.0075),  # +1.0%      -> lock +0.75%
    (0.018, 0.0110),  # +1.8%      -> lock +1.10%  (Mike's "1% on 10k" rung)
    (0.030, 0.0200),  # +3.0%      -> lock +2.00%
    (0.050, 0.0340),  # +5.0%      -> lock +3.40%
    (0.100, 0.0500),  # +10%       -> lock +5.00%  (kept from the 6/13 ladder)
)

# DCA accumulation profit lock (crypto). DCA targets are smaller (per-coin
# ~6%), so the rungs are tighter: protect capital early, lock a little after.
# Same replay, same verdict, plus one of its own: the +3% rung locked
# BREAKEVEN, and breakeven on crypto is a 0.62% LOSS once the round trip is
# paid. DCA armed on 1 of 25 trades in 30 days. Retuned it improves the
# month from -$555 to -$512 -- real, but small, because DCA's problem is
# not the exit. 25 trades on $55.7k of notional bleeding half a thousand
# dollars is an ENTRY-quality problem, and no exit rule fixes it. Mike
# 2026-08-19: fix the DCA entries first, then revisit these rungs.
DCA_PROFIT_LADDER = (
    (0.008, 0.0065),  # +0.8% peak -> lock +0.65%
    (0.010, 0.0075),  # +1.0%      -> lock +0.75%
    (0.018, 0.0110),  # +1.8%      -> lock +1.10%
    (0.030, 0.0200),  # +3.0%      -> lock +2.00%
    (0.050, 0.0340),  # +5.0%      -> lock +3.40%
)

# Extended (STOCK multi-day swing) profit lock. Bigger moves than crypto DCA,
# so wider rungs. Kept here with the other ladders as one tunable home; the
# Position Monitor applies it to Alpaca-routed Extended rows.
#
# DELIBERATELY NOT RETUNED by the 2026-08-19 crypto rung replay. That study
# covered crypto longs only, where a 0.62% round trip eats the small moves.
# Alpaca equities are commission-free, so a breakeven rung here is genuinely
# breakeven, not a hidden loss. Retuning this on crypto evidence would be
# borrowing a conclusion from a different cost model.
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


def ladder_clears_fees(ladder, fee_bps: float, slippage_bps: float
                       ) -> list[tuple[float, float]]:
    """Every rung whose LOCKED FLOOR sits at or below round-trip cost.

    A rung that locks +0.00% (or anything under 0.62%) exits at a NET LOSS
    while the activity log cheerfully says "profit locked". That is the
    failure this repo cares most about: a loss wearing the costume of a win.
    Returns the offending rungs -- empty list means the ladder is safe.

    Added 2026-08-19 with the retuned rungs, because the old DCA ladder's
    first rung WAS +0.00% and had been for two months without anyone -- me
    included -- noticing that it could not make money."""
    floor = round_trip_cost_pct(fee_bps, slippage_bps)
    bad: list[tuple[float, float]] = []
    for trigger, locked in ladder:
        if float(locked) <= floor:
            bad.append((float(trigger), float(locked)))
    return bad


def ladder_is_monotonic(ladder) -> bool:
    """True when both triggers and locked floors climb strictly. A ladder
    that dips (the 6/13 SWING ladder went +8%->+3% AFTER +5%->+0%, then
    +10%->+5%) means a HIGHER peak can propose a LOWER stop; the ratchet
    then silently ignores the rung and the tier reads as active when it is
    not."""
    trigs = [float(t) for t, _ in ladder]
    locks = [float(f) for _, f in ladder]
    return (all(b > a for a, b in zip(trigs, trigs[1:]))
            and all(b > a for a, b in zip(locks, locks[1:])))


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


def _broker_tradable_filter(syms: list[str]) -> list[str]:
    """Broker-only mode (Mike 2026-07-28): keep only coins Alpaca can
    actually execute, so every crypto row in Trezo also appears on his
    Alpaca screen. Fails OPEN (returns the list unchanged) if the asset
    list cannot be read -- a data hiccup must never silently empty the
    universe."""
    try:
        from app.config import get_settings as _gs
        if not bool(getattr(_gs(), "trezo_broker_only", False)):
            return syms
    except Exception:  # noqa: BLE001
        return syms
    try:
        from app.brokers.alpaca import tradable_crypto_symbols
        ok = tradable_crypto_symbols()
        if not ok:
            return syms
        return [s for s in syms if s.upper() in ok]
    except Exception:  # noqa: BLE001
        return syms


def _union_discovered(seed: list[str]) -> list[str]:
    """2026-07-23: fold in the expander's enrolled coins. (The
    watchlist_tickers table this union was designed for never existed
    in this deployment -- the DB path always fell back -- so the
    file-backed expander is the real expansion mechanism.)"""
    try:
        from app.data.crypto_discovery import discovered_symbols
        for d in discovered_symbols():
            if d not in seed:
                seed.append(d)
    except Exception:  # noqa: BLE001
        pass
    return _broker_tradable_filter(seed)


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
            return _union_discovered(list(CRYPTO_WATCHLIST))
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
        return _union_discovered(seed)
    except Exception:  # noqa: BLE001
        return _union_discovered(list(CRYPTO_WATCHLIST))


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
# DCA BOUNCE GATE (2026-08-19, Mike: "DCA is having an issue of its own
# lane"). 30-day audit: DCA was the only mode whose entire entry condition
# was `rsi < 40` -- no bands, no volume, no trend, nothing asking whether
# the fall had STOPPED. RSI under 40 means the coin is falling; buying on
# that alone is catching knives, and the month priced it: 29 closes,
# -$738, most never bouncing even +0.8% after entry because the bounce
# had not started when we bought. Every other mode earns its entry; now
# DCA does too: oversold AND turning up. Set to 0 to restore knife-catching.
DCA_REQUIRE_BOUNCE = _envf("TREZO_CRYPTO_DCA_REQUIRE_BOUNCE", 1) >= 1


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
            # (SWING replaces rather than rescales; the guard below reports
            #  the ratio change so an override is as visible as a rescale.)
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

    # --- DCA: oversold accumulation -- of a coin that has STOPPED falling.
    # Oversold alone is not a reason to buy; it is a description of the
    # fall. The bounce gate demands the first evidence of recovery: RSI
    # higher than the previous bar AND the last close above the one before
    # it. Same coins, same discipline, one word added: bounce. ---
    if rsi_now < DCA_RSI_MAX:
        _rsi_series = rsi(cl, 14)
        _rsi_prev = _rsi_series[-2] if len(_rsi_series) >= 2 else rsi_now
        _bouncing = (rsi_now > _rsi_prev) and (cl[-1] > cl[-2])
        if _bouncing or not DCA_REQUIRE_BOUNCE:
            return CryptoSignal(
                ticker=sym, mode="dca", direction="bullish",
                stop_pct=base["stop_pct"], target_pct=base["target_pct"],
                rsi=rsi_now, bb_width_pct=bb_w, volume_ratio=vol_ratio,
                reason=(f"DCA - RSI {rsi_now:.0f} oversold and turning up "
                        f"(prev {_rsi_prev:.0f}), buying the bounce."),
            )
        # Oversold but still falling: the old code bought exactly here.
        # No signal -- and deliberately no fall-through to SCALP below,
        # because a coin with RSI under 40 mid-fall is not a calm range
        # coin either. Held off is the trade.
        return None

    # --- SCALP: fast, flexible default for calm/range coins. Loose bands,
    # volume-OPTIONAL so it is not frozen out on no-volume feeds. ---
    if (bb_w < SCALP_BB_MAX and SCALP_RSI_LO <= rsi_now <= SCALP_RSI_HI
            and (vol_ratio >= SCALP_VOL_MIN or not has_vol)):
        # GEOMETRY GUARD (2026-08-05). These two multipliers DIFFER, so
        # the designed 1:2 leaves here as 1:1.67. That is a real change
        # and it went unnoticed for weeks -- the only trace was four
        # stop-outs clustering at -1.9%. The rescale is not blocked (a
        # reporting guard that can stop a trade is a new failure mode),
        # but it can no longer happen quietly. Scaling both legs by the
        # same factor would preserve the ratio.
        _s_scalp = max(base["stop_pct"] * 0.6, 0.01)
        _t_scalp = max(base["target_pct"] * 0.5, 0.02)
        try:
            from app.runtime.geometry import check_rescale
            check_rescale(sym, "crypto_scalp",
                          base["stop_pct"], base["target_pct"],
                          _s_scalp, _t_scalp,
                          note="SCALP multipliers stop x0.6, target x0.5")
        except Exception:  # noqa: BLE001
            pass
        return CryptoSignal(
            ticker=sym, mode="scalp", direction="bullish",
            stop_pct=_s_scalp,
            target_pct=_t_scalp,
            rsi=rsi_now, bb_width_pct=bb_w, volume_ratio=vol_ratio,
            reason=f"SCALP - BB {bb_w:.1f}% range, RSI {rsi_now:.0f}, vol {vol_ratio:.1f}x.",
        )

    return None
