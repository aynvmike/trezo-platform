"""Account posture & capital allocation.

Phase 8a.2. Trezo reads the live account size and the AI picks a default
*posture*:

  - small account  (< $25k)        -> 'growth'   (build the account up)
  - mid account     ($25k-$100k)   -> 'balanced'
  - large account   (>= $100k)     -> 'income'   (generate income, preserve)

The posture splits equity into per-market-type dollar budgets — how much
may be deployed into crypto vs stocks vs options vs income strategies at
once. The Trade Execution agent caps each new trade by the remaining
budget for its market type.

Profit-taking (the Daily Profit Lock) stays available at every account
size and in every posture — the posture only changes WHERE capital is
deployed and whether gains lean toward compounding or locking.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, asdict
from typing import Optional

from app.config import get_settings


POSTURES = ("growth", "balanced", "income", "velocity")
MARKET_TYPES = ("crypto", "stocks", "options", "income", "forex")

# Per-posture split of equity across market types (fractions, sum to 1.0).
# Forex added 2026-07-02 (modeled engine, Kraken data): a small dedicated
# pocket carved from stocks+crypto so FX trades never eat the other lanes.
POSTURE_SPLIT: dict[str, dict[str, float]] = {
    "growth":   {"crypto": 0.32, "stocks": 0.42, "options": 0.10, "income": 0.10, "forex": 0.06},
    "balanced": {"crypto": 0.18, "stocks": 0.32, "options": 0.20, "income": 0.25, "forex": 0.05},
    "income":   {"crypto": 0.09, "stocks": 0.18, "options": 0.20, "income": 0.48, "forex": 0.05},
    # VELOCITY (Mike 2026-07-24): "prioritize the trades that can be
    # settled in a day, the 24-hour market, and things that are liquid
    # so we can reach a daily profit goal." Capital cycles instead of
    # parking: 24/7 lanes (crypto+forex = 48%) and fast option cycles
    # (same-day lane + weekly wheel) weighted first; multi-day stock
    # swings get the smallest share they've ever had. Opt-in only via
    # the account_posture setting -- auto never picks it.
    "velocity": {"crypto": 0.40, "stocks": 0.22, "options": 0.22, "income": 0.08, "forex": 0.08},
}

# How each posture leans on realized gains.
POSTURE_PROFIT_MODE = {
    "growth": "compound",       # keep gains working in the account
    "balanced": "balanced",
    "income": "lock_heavy",     # move gains to the vault sooner
    "velocity": "compound",     # daily gains stay working -- velocity IS the point
}

POSTURE_SUMMARY = {
    "growth": "Smaller account — growth focus: build the balance up, lean into the higher-return layers.",
    "balanced": "Mid-size account — balanced: capital spread across growth and income.",
    "income": "Larger account — income focus: tilt to the Wheel and Dividends layers, preserve capital.",
    "velocity": "Daily-income focus: 24/7 markets and same-day cycles weighted first; capital re-cycles daily instead of parking.",
}


async def effective_equity(user_id: str) -> float:
    """The equity pockets are sized from. Prefers the BROKER's account
    equity (the truth about buying power) when Alpaca is configured; falls
    back to the internal ledger (cash + vault). Decision 2026-07-02: the
    internal ledger had drifted ($2.8k) from the broker ($4.8k), silently
    shrinking every pocket by ~40%."""
    try:
        from app.brokers.alpaca import alpaca_configured
        from app.brokers.alpaca import get_account as _broker_account
        if alpaca_configured():
            acct = await _broker_account()
            if acct is not None:
                _eq = float(getattr(acct, "equity", 0) or 0)
                if _eq > 0:
                    return _eq
    except Exception:  # noqa: BLE001
        pass
    try:
        from app.paper.engine import get_account
        account = await get_account(user_id)
        if account:
            return (float(account.get("current_cash_usd") or 0)
                    + float(account.get("vault_balance_usd") or 0))
    except Exception:  # noqa: BLE001
        pass
    return 0.0


def position_pct_for_equity(equity: float) -> float:
    """Per-trade notional cap as a fraction of equity -- Mike's account-
    size curve (2026-07-08): "a small account can not afford that move
    for long compared to a larger account; with $20k it can really rely
    on 1-2% profits on $5-10k trades."
      < $10k   -> 15%   (protect longevity -- no oversized swings)
      $10-25k  -> 30%   (quick 1-2% plays on size become viable)
      $25-100k -> 25%
      >= $100k -> 15%   (conservative at scale)
    TREZO_MAX_POSITION_PCT forces a flat cap when set; the user's
    bot_settings.max_position_pct slider still overrides everything."""
    import os as _os
    _flat = _os.getenv("TREZO_MAX_POSITION_PCT")
    if _flat:
        try:
            v = float(_flat)
            if 0.01 <= v <= 1.0:
                return v
        except (TypeError, ValueError):
            pass
    e = float(equity or 0)
    if e < 10_000:
        return 0.15
    if e < 25_000:
        return 0.30
    if e < 100_000:
        return 0.25
    return 0.15


def default_posture(equity: float) -> str:
    """The AI's default posture, chosen purely from account size."""
    if equity < 25_000:
        return "growth"
    if equity < 100_000:
        return "balanced"
    return "income"


def market_type_for(strategy: str, asset_type: str) -> str:
    """Map a trade's strategy + asset type to one of the MARKET_TYPES buckets."""
    s = (strategy or "").lower()
    at = (asset_type or "").lower()
    if at == "forex" or s.startswith("forex"):
        return "forex"
    if at == "crypto" or s.startswith("crypto"):
        return "crypto"
    if s.startswith("wheel"):
        return "income"
    if s.startswith("options") or at == "option" or s in (
        "long_call", "bull_call_spread", "cash_secured_put"
    ):
        return "options"
    return "stocks"


@dataclass
class AllocationPlan:
    posture: str
    source: str                 # 'auto' (AI chose) or 'user'
    account_equity: float
    budgets: dict               # market_type -> dollar budget
    profit_mode: str
    summary: str

    def to_dict(self) -> dict:
        return asdict(self)


def build_allocation(
    equity: float,
    posture_setting: str = "auto",
    overrides: Optional[dict] = None,
) -> AllocationPlan:
    """Build the capital-allocation plan for an account.

    posture_setting: 'auto' (let the AI choose by size) or an explicit
    posture. overrides: optional {market_type: dollar_budget} from the user.
    """
    equity = max(0.0, float(equity or 0))
    if posture_setting in POSTURES:
        posture, source = posture_setting, "user"
    else:
        posture, source = default_posture(equity), "auto"

    split = POSTURE_SPLIT.get(posture, POSTURE_SPLIT["growth"])
    budgets = {mt: round(equity * split[mt], 2) for mt in MARKET_TYPES}

    if overrides:
        for mt, val in overrides.items():
            if mt in MARKET_TYPES:
                try:
                    budgets[mt] = max(0.0, float(val))
                except (TypeError, ValueError):
                    pass

    return AllocationPlan(
        posture=posture,
        source=source,
        account_equity=round(equity, 2),
        budgets=budgets,
        profit_mode=POSTURE_PROFIT_MODE[posture],
        summary=POSTURE_SUMMARY[posture],
    )


def _supabase():
    s = get_settings()
    if not s.supabase_url or not s.supabase_service_role_key:
        return None
    try:
        from supabase import create_client
        return create_client(s.supabase_url, s.supabase_service_role_key)
    except Exception:  # noqa: BLE001
        return None


async def deployed_capital(user_id: str) -> dict[str, float]:
    """Sum the notional of this user's OPEN positions, grouped by market
    type — so the Trade Execution agent knows how much budget is left."""
    out = {mt: 0.0 for mt in MARKET_TYPES}
    client = _supabase()
    if not client:
        return out

    def _sync():
        return (
            client.table("paper_positions")
            .select("asset_type, strategy, quantity, entry_price")
            .eq("user_id", user_id)
            .eq("status", "open")
            .execute()
        )

    try:
        res = await asyncio.to_thread(_sync)
    except Exception:  # noqa: BLE001
        return out
    for r in res.data or []:
        try:
            notional = float(r.get("quantity") or 0) * float(r.get("entry_price") or 0)
        except (TypeError, ValueError):
            continue
        mt = market_type_for(r.get("strategy") or "", r.get("asset_type") or "")
        out[mt] = out.get(mt, 0.0) + notional
    return out
