"""Strategy bucket classification + per-user hopeful allocation lookup.

Used by Options Scanner (cap-at-emit), Risk Manager (cap-at-approve),
and Exit Advisor Options (cap-near alerts). Single source of truth so
the three agents can never disagree on which strategy is hopeful.

Wired by Nova for Mike 2026-06-02 (Path beta).
"""

from __future__ import annotations

import asyncio
from typing import Any

# Strategies that count toward Mike's 3% hopeful-holds cap.
# Per project_options_trading_rules.md rule 5: directional long
# calls / debit spreads outside the Wheel - the "hopeful" bucket.
HOPEFUL_STRATEGIES = frozenset({
    "long_call", "long_put", "bull_call_spread",
})

# Strategies the Wheel manages directly. NEVER counted toward hopeful.
WHEEL_STRATEGIES = frozenset({"wheel_csp", "wheel_cc"})

# Anything else is income-style premium-sell or unknown - bucket as income.


def strategy_bucket(strategy: str) -> str:
    """Return 'wheel' | 'income' | 'hopeful'. Stable, side-effect-free."""
    s = (strategy or "").lower()
    if s in WHEEL_STRATEGIES:
        return "wheel"
    if s in HOPEFUL_STRATEGIES:
        return "hopeful"
    return "income"


def is_hopeful(strategy: str) -> bool:
    return strategy_bucket(strategy) == "hopeful"


async def hopeful_allocation_pct(client, user_id: str) -> float:
    """Return the user's current open hopeful allocation as a fraction
    of total options capital. 0.0 when no positions or query fails -
    fail OPEN so a quiet DB does not lock the user out.
    """
    if not client or not user_id:
        return 0.0

    def _sync():
        return (
            client.table("options_positions")
            .select("strategy, contracts, strike, net_premium_usd")
            .eq("user_id", user_id)
            .eq("status", "open")
            .execute()
        )
    try:
        res = await asyncio.to_thread(_sync)
        rows = res.data or []
    except Exception:  # noqa: BLE001
        return 0.0

    total_capital = 0.0
    hopeful_capital = 0.0
    for r in rows:
        strat = str(r.get("strategy") or "")
        bucket = strategy_bucket(strat)
        contracts = int(r.get("contracts") or 1)
        strike = float(r.get("strike") or 0.0)
        premium = float(r.get("net_premium_usd") or 0.0)
        if bucket == "wheel" and "csp" in strat:
            cap = strike * 100.0 * contracts
        elif premium < 0:  # debit position
            cap = abs(premium)
        else:
            cap = strike * 100.0 * contracts * 0.1
        total_capital += cap
        if bucket == "hopeful":
            hopeful_capital += cap

    if total_capital <= 0:
        return 0.0
    return hopeful_capital / total_capital


def hopeful_cap_for_user(user_id: str | None) -> float:
    """Return the user's hopeful allocation cap as a fraction. Reads
    the per-user override from bot_settings, falls through to the
    env default. Returns the global default on any failure."""
    try:
        from app.config import get_settings
        s = get_settings()
        env_default = float(s.options_hopeful_allocation_cap_pct or 0.03)
    except Exception:  # noqa: BLE001
        env_default = 0.03

    if not user_id:
        return env_default

    try:
        from app.runtime.settings import get_bot_settings
        bs = get_bot_settings(user_id)
        per_user = bs.options_hopeful_allocation_cap_pct
        if per_user is not None:
            return float(per_user)
    except Exception:  # noqa: BLE001
        pass

    return env_default
