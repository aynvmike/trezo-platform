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


# --- Experience-driven risk-gate nudge (2026-06-16, opt-in) ---------------
# Bounded + asymmetric toward caution: a proven winner trades a bit more
# freely; a proven loser needs much higher conviction. Used by risk_manager
# only when settings.outcome_gate_tuning_enabled is true.
_FLOOR_RELAX_FAVOR = -25    # favor -> lower the TCS bar modestly
_FLOOR_TIGHTEN_AVOID = 75   # avoid -> raise the bar a lot


def floor_delta_for(edge: "dict[str, dict]", strategy: str) -> int:
    """TCS-floor delta for a strategy from its live verdict. favor -> -25,
    avoid -> +75, else 0. Bounded; 0 when data is insufficient."""
    v = edge_verdict(edge, strategy)
    if v == "favor":
        return _FLOOR_RELAX_FAVOR
    if v == "avoid":
        return _FLOOR_TIGHTEN_AVOID
    return 0
