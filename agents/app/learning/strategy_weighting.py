"""Outcome-weighted strategy edge (2026-06-16).

Turns realized trade_outcomes stats (learning.outcomes.get_strategy_stats)
into a per-strategy "edge" the selector and risk gates can lean on, so the
agents actually get BETTER from past results instead of only surfacing the
numbers for the user to act on manually.

Design rules (Mike's "all, honestly"):
  - DATA-GATED: a strategy needs >= MIN_TRADES closed trades before its
    record can influence anything. Below that it is "insufficient_data" and
    the caller falls back to its existing behavior, unchanged.
  - FALLBACK-SAFE: every consumer treats a missing/insufficient edge as
    "no opinion", so the loop can never make a thin-data bot worse.
  - BOUNDED: verdicts are coarse (favor / neutral / avoid), not raw knobs,
    so a noisy sample cannot swing selection or floors wildly.
"""

from __future__ import annotations

import time
from typing import Any, Optional

MIN_TRADES = 8             # below this a strategy's live record is ignored
# Growth-profit tilt (Mike 2026-07-27: "focus on growth profit driven
# income"). The 8-trade minimum is a STATISTICAL sample size, not a PDT
# rule -- judging a strategy on three lucky trades is how a bot talks
# itself into a bad lane. It stays. What changes: a strategy that has
# EARNED its sample gets its reward recognised at a lower bar than a
# penalty, because holding back a proven winner costs real income while
# tolerating an unproven one only risks a small position.
MIN_TRADES_REWARD = int(__import__("os").getenv(
    "TREZO_LEARN_MIN_TRADES_REWARD", "6"))
_FAVOR_WIN_RATE = 0.45     # favor needs win rate at/above this AND +expectancy
_AVOID_WIN_RATE = 0.35     # avoid needs win rate below this AND <=0 expectancy

_CACHE_TTL = 600.0         # 10 min; realized outcomes move slowly
_cache: "dict[str, tuple[dict, float]]" = {}


def _verdict(n: int, win_rate: Optional[float], expectancy: float) -> str:
    if n < MIN_TRADES or win_rate is None:
        return "insufficient_data"
    if expectancy > 0.0 and win_rate >= _FAVOR_WIN_RATE:
        return "favor"
    if expectancy <= 0.0 and win_rate < _AVOID_WIN_RATE:
        return "avoid"
    return "neutral"


def compute_strategy_edge(by_strategy: "dict[str, Any]") -> "dict[str, dict]":
    """Pure: map get_strategy_stats()['by_strategy'] -> per-strategy edge.
    Each value: {n, win_rate, expectancy_usd, verdict}. Safe on empty input."""
    out: "dict[str, dict]" = {}
    for strat, st in (by_strategy or {}).items():
        n = int(st.get("n") or 0)
        wr = st.get("win_rate")
        total = float(st.get("total_pnl_usd") or 0.0)
        expectancy = round(total / n, 2) if n > 0 else 0.0
        out[str(strat)] = {
            "n": n,
            "win_rate": wr,
            "expectancy_usd": expectancy,
            "verdict": _verdict(n, wr, expectancy),
        }
    return out


async def get_live_strategy_edge(user_id: str, lookback_days: int = 45) -> "dict[str, dict]":
    """Per-user strategy edge from realized outcomes, cached 10 min. Returns
    {} (no opinion) on any failure or when learning isn't configured."""
    if not user_id:
        return {}
    key = str(user_id)
    now = time.time()
    hit = _cache.get(key)
    if hit is not None and (now - hit[1]) < _CACHE_TTL:
        return hit[0]
    try:
        from app.learning.outcomes import get_strategy_stats
        stats = await get_strategy_stats(user_id, lookback_days=lookback_days)
        edge = compute_strategy_edge(stats.get("by_strategy") or {})
    except Exception:  # noqa: BLE001
        edge = {}
    _cache[key] = (edge, now)
    return edge


def edge_verdict(edge: "dict[str, dict]", strategy: str) -> str:
    """Verdict for one strategy; 'insufficient_data' when unknown."""
    e = (edge or {}).get(str(strategy))
    return e.get("verdict", "insufficient_data") if e else "insufficient_data"


def growth_reward_ready(edge: "dict[str, dict]", strategy: str) -> bool:
    """True when a strategy has earned recognition on the REWARD side at
    MIN_TRADES_REWARD closes (default 6) rather than the full 8.

    Growth-profit tilt (Mike 2026-07-27). Asymmetric on purpose: holding
    a proven winner back costs real income every day it waits, while
    letting an unproven lane trade a slightly smaller position only
    risks one capped bet. The PENALTY side keeps the full 8-trade
    sample -- punishment still needs proof."""
    e = (edge or {}).get(str(strategy)) or {}
    try:
        n = int(e.get("trades") or e.get("n") or 0)
        pf = float(e.get("profit_factor") or e.get("pf") or 0)
    except (TypeError, ValueError):
        return False
    return n >= MIN_TRADES_REWARD and pf >= 1.5


# --- Experience-driven risk-gate nudge (2026-06-16, opt-in) ---------------
# Bounded + asymmetric toward caution: a proven winner trades a bit more
# freely; a proven loser needs much higher conviction. Used by risk_manager
# only when settings.outcome_gate_tuning_enabled is true.
# RESCALED 2026-07-27 (Mike's audit). These were written on the OLD
# 1000-point TCS scale and never converted -- the same bug class as the
# regime posture (+25..+150) and the Bot Tuning slider (min 300). On
# today's 0-100 scale, -25 was a collapse of the bar and +75 made a
# strategy permanently untradeable. Re-expressed to match every other
# live bump: regime <= +15, goal +5, margin +8.
# Still asymmetric toward caution: a proven winner earns a small
# discount, a proven loser pays a large premium.
_FLOOR_RELAX_FAVOR = -3     # favor -> a modest discount on the bar
_FLOOR_TIGHTEN_AVOID = 12   # avoid -> a heavy premium, but not a ban


def floor_delta_for(edge: "dict[str, dict]", strategy: str) -> int:
    """TCS-floor delta for a strategy from its live verdict. favor -> -25,
    avoid -> +75, else 0. Bounded; 0 when data is insufficient."""
    v = edge_verdict(edge, strategy)
    if v == "favor":
        return _FLOOR_RELAX_FAVOR
    if v == "avoid":
        return _FLOOR_TIGHTEN_AVOID
    return 0
