"""Market-cap tiers -- the per-tier FORMULA layer (Mike 2026-07-02).

One-size stop/target formulas treat a $3T mega-cap like a $200M micro-cap.
They are different animals: megas move ~1%/day and reward TIGHT, quick
profit-taking; micros move 10%+ and need room (wider stops, wider targets,
smaller size via the risk math). This module classifies a ticker into a
cap tier and scales any strategy's stop/target accordingly. The Risk
Manager applies it as the LAST formula step before approval, after the
Adaptive-Scope regime multiplier.

Tier data: Finnhub profile2 marketCapitalization (millions USD), cached
in-process for 24h per symbol; falls back to "unknown" (neutral, mid-tier
multipliers x1.0) so a data miss can never distort a trade.

NO price floors here, by design (Mike 2026-06-15: never gate on price).
"""

from __future__ import annotations

import time as _time
from typing import Optional

# Tier floors in MILLIONS of USD, checked in order.
TIER_THRESHOLDS_M: tuple[tuple[str, float], ...] = (
    ("mega", 200_000.0),   # >= $200B
    ("large", 10_000.0),   # >= $10B
    ("mid", 2_000.0),      # >= $2B
    ("small", 300.0),      # >= $300M
)
# Anything below $300M is micro.

# Per-tier formula profile. stop/target multipliers scale whatever the
# strategy asked for; scalp_ok marks tiers liquid enough for quick
# in-and-out trades; min_avg_vol is a SUGGESTED liquidity bar for
# scanners (the risk gate keeps its own tunable floor).
TIER_PROFILES: dict[str, dict] = {
    "mega":    {"stop_mult": 0.80, "target_mult": 0.70, "scalp_ok": True,
                "min_avg_vol": 1_000_000},
    "large":   {"stop_mult": 0.90, "target_mult": 0.85, "scalp_ok": True,
                "min_avg_vol": 750_000},
    "mid":     {"stop_mult": 1.00, "target_mult": 1.00, "scalp_ok": False,
                "min_avg_vol": 400_000},
    "small":   {"stop_mult": 1.25, "target_mult": 1.30, "scalp_ok": False,
                "min_avg_vol": 250_000},
    "micro":   {"stop_mult": 1.60, "target_mult": 1.80, "scalp_ok": False,
                "min_avg_vol": 250_000},
    "unknown": {"stop_mult": 1.00, "target_mult": 1.00, "scalp_ok": False,
                "min_avg_vol": 400_000},
}

_TIER_CACHE: dict[str, tuple[float, str]] = {}
_TIER_TTL = 86_400.0  # cap tier barely moves intraday


def tier_from_cap_millions(cap_m: Optional[float]) -> str:
    if cap_m is None or cap_m <= 0:
        return "unknown"
    for tier, floor in TIER_THRESHOLDS_M:
        if cap_m >= floor:
            return tier
    return "micro"


async def tier_for(symbol: str, price: Optional[float] = None) -> str:
    """Cap tier for `symbol`. Best-effort + cached; 'unknown' on any miss."""
    sym = (symbol or "").upper().strip()
    if not sym:
        return "unknown"
    hit = _TIER_CACHE.get(sym)
    if hit and (_time.time() - hit[0]) < _TIER_TTL:
        return hit[1]
    cap_m: Optional[float] = None
    try:
        from app.data.fundamentals import market_cap_millions
        cap_m = await market_cap_millions(sym)
    except Exception:  # noqa: BLE001
        cap_m = None
    if (cap_m is None or cap_m <= 0) and price and price > 0:
        # Fallback: shares outstanding x price.
        try:
            from app.data.fundamentals import shares_outstanding_millions
            sh_m = await shares_outstanding_millions(sym)
            if sh_m and sh_m > 0:
                cap_m = sh_m * float(price)
        except Exception:  # noqa: BLE001
            pass
    tier = tier_from_cap_millions(cap_m)
    # Cache misses too (shorter TTL) so a gated API isn't hammered.
    ttl_key = _time.time() if tier != "unknown" else (_time.time() - _TIER_TTL + 3600.0)
    _TIER_CACHE[sym] = (ttl_key, tier)
    return tier


def profile(tier: str) -> dict:
    return TIER_PROFILES.get(tier or "unknown", TIER_PROFILES["unknown"])


def adjust_stop_target(tier: str, stop_pct: Optional[float],
                       target_pct: Optional[float]
                       ) -> tuple[Optional[float], Optional[float]]:
    """Scale a strategy's stop/target for the tier. None passes through."""
    p = profile(tier)
    s = round(float(stop_pct) * p["stop_mult"], 4) if stop_pct is not None else None
    t = round(float(target_pct) * p["target_mult"], 4) if target_pct is not None else None
    return s, t


def scalp_ok(tier: str) -> bool:
    return bool(profile(tier).get("scalp_ok"))
