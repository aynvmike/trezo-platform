"""Capital sleeves -- horizon-based allocation (Part 1-2, 2026-06-17).

Mike thinks in time-horizons, not asset classes. This module sits on top of
allocation.py (which buckets by market type) and divides account equity into
three SLEEVES by how long a trade is meant to live:

  - active   intraday -> next-day plays            (Layers 1-short, 2, 4)
  - options  2-3 day directional option plays      (Layer 3) -> +30% take & recycle
  - holding  days-to-indefinite income / holds     (Layers 1-hold, 5, 6)

WHY THIS EXISTS
The old pool had ONE cap (max_open_positions, default 3) and sized each trade
at up to 25% of equity, with capital split only by asset class. Whatever
scanner fired first grabbed the open slots -- almost always the fast stock
day-trade scanners -- so a couple of names ate the buying power and the Wheel,
crypto, options and dividend layers never got funded. Sleeves give each
horizon its OWN reserved budget so the layer system finally has teeth at the
capital level, plus per-strategy / per-ticker caps that stop the same strategy
being stacked across names.

SPLIT RIDES THE RISK DIAL
The split between sleeves follows the account risk profile
(conservative / balanced / aggressive), NOT fixed dollars, so it scales with
the account. 'balanced' reproduces Mike's $2k / $1k / $2k on a $5k account.

SOFT BUDGETS WITH A PROVEN-TRADE OVERRIDE
A sleeve over budget is HELD (warned + skipped), NOT hard-blocked -- except a
strategy whose REAL logged win-rate clears the proven bar (default 75% over
>= MIN_PROVEN_TRADES closed trades) is waved through, up to a hard breach
ceiling (default 1.5x the sleeve budget). Proven data beats a static budget;
this is the experience-driven principle the learning loop already follows.

SCOPE: Part 1 defined the policy + pure helpers. Part 2 adds deployed_by_sleeve
(live sum of open notional per sleeve) and compute_slot (the per-trade gate
decision the Trade Execution agent calls). Forex is deferred.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, asdict
from typing import Optional


SLEEVES = ("active", "options", "holding")

SLEEVE_LABEL = {
    "active":  "Active (intraday -> next-day)",
    "options": "Quick Options (2-3 day)",
    "holding": "Holding (income / longer)",
}

# Per-profile split of equity across sleeves (fractions, sum to 1.0).
# 'balanced' == Mike's stated $2k / $1k / $2k on a $5k account.
SLEEVE_SPLIT: dict[str, dict[str, float]] = {
    "conservative": {"active": 0.25, "options": 0.10, "holding": 0.65},
    "balanced":     {"active": 0.40, "options": 0.20, "holding": 0.40},
    "aggressive":   {"active": 0.50, "options": 0.25, "holding": 0.25},
}
_DEFAULT_PROFILE = "balanced"

# Plain-English horizon + profit template per sleeve (the agents' "template").
SLEEVE_HOLD = {
    "active":  "Open intraday; exit by end of day or carry one session at most.",
    "options": "Hold 2-3 days max.",
    "holding": "Days to indefinite (wheel cycles, dividends, crypto accumulation).",
}
SLEEVE_PROFIT = {
    "active":  "Quick profit-based exits; ride the ladder stops.",
    "options": "Take profit at +30% and recycle into the options sleeve.",
    "holding": "Lock with ladders, collect premium, let dividends compound.",
}
# Machine hints for Part 3 wiring.
SLEEVE_TAKE_PROFIT_PCT = {"active": None, "options": 0.30, "holding": None}
SLEEVE_MAX_HOLD = {"active": "next_session", "options": "3_days", "holding": "open"}
# Concrete day ceilings the position monitor enforces (0 = no cap, held by
# design). Tunable. Holding = wheel/dividends/HODL.
SLEEVE_MAX_HOLD_DAYS = {"active": 5, "options": 4, "holding": 0}

# Layer membership (the 7 Woven Basket layers) per sleeve, for the UI + doc.
SLEEVE_LAYERS = {
    "active":  ("2 Stock intraday (STMS/ORB/pattern)", "1 Crypto short (scalp/swing)", "4 Stock weekly (extended)"),
    "options": ("3 Options engine (directional calls / spreads)",),
    "holding": ("5 Wheel", "6 Dividends", "1 Crypto hold (HODL/DCA)", "7 Quality cores"),
}

# Default position caps per sleeve. max_per_strategy is the duplicate-strategy
# guard (the "two of the same strategy" problem). All tunable later.
SLEEVE_CAPS: dict[str, dict[str, int]] = {
    "active":  {"max_positions": 3, "max_per_strategy": 2, "max_per_ticker": 1},
    "options": {"max_positions": 4, "max_per_strategy": 3, "max_per_ticker": 1},
    "holding": {"max_positions": 6, "max_per_strategy": 3, "max_per_ticker": 2},
}

# Proven-trade override knobs (Mike: "75 percent and higher for the orb ...").
PROVEN_WIN_RATE = 0.75      # logged win-rate bar to breach a full sleeve
MIN_PROVEN_TRADES = 10      # need this many closed trades to trust the rate
MAX_BREACH_MULT = 1.5       # a proven trade may push a sleeve to 1.5x budget, no more


def _norm(s: Optional[str]) -> str:
    return (s or "").strip().lower()


def sleeve_for(strategy: str, asset_type: str = "") -> str:
    """Map a trade's strategy (+ asset type) to one of the SLEEVES."""
    s = _norm(strategy)
    at = _norm(asset_type)

    # Crypto: accumulation / hold -> holding; scalp / swing / other -> active.
    if at == "crypto" or s.startswith("crypto"):
        if any(k in s for k in ("hodl", "dca", "accumul")):
            return "holding"
        return "active"

    # Income / holding strategies.
    if s.startswith("wheel"):
        return "holding"
    if "dividend" in s or "yieldmax" in s:
        return "holding"
    if "quality" in s or s == "core":
        return "holding"

    # Directional options -> options sleeve (wheel CSP already handled above).
    if at == "option" or s.startswith("options") or s in (
        "long_call", "long_put", "bull_call_spread", "bull_put_spread",
        "iron_condor", "cash_secured_put", "iv_crush_short",
    ):
        return "options"

    # Stock intraday + multi-day swing -> active. (extended is a judgment call;
    # it lives in active as an actively-managed directional swing -- tunable.)
    return "active"


@dataclass
class SleevePlan:
    profile: str
    source: str                 # 'user' (explicit profile/overrides) or 'default'
    account_equity: float
    budgets: dict               # sleeve -> dollar budget
    caps: dict                  # sleeve -> {max_positions, max_per_strategy, max_per_ticker}
    summary: str

    def to_dict(self) -> dict:
        return asdict(self)


def _resolve_profile(profile_setting: str) -> "tuple[str, str]":
    p = _norm(profile_setting)
    if p in SLEEVE_SPLIT:
        return p, "user"
    # expert / auto / unknown -> balanced base (overrides may reshape it).
    return _DEFAULT_PROFILE, "default"


def build_sleeves(
    equity: float,
    profile_setting: str = "balanced",
    overrides: Optional[dict] = None,
) -> SleevePlan:
    """Build the sleeve budget plan for an account.

    profile_setting: 'conservative' | 'balanced' | 'aggressive' (the risk
    dial). Anything else falls back to balanced. overrides: optional
    {sleeve: dollar_budget} for expert users.
    """
    equity = max(0.0, float(equity or 0))
    profile, source = _resolve_profile(profile_setting)
    split = SLEEVE_SPLIT[profile]
    budgets = {sl: round(equity * split[sl], 2) for sl in SLEEVES}

    if overrides:
        for sl, val in overrides.items():
            if sl in SLEEVES:
                try:
                    budgets[sl] = max(0.0, float(val))
                except (TypeError, ValueError):
                    pass
        source = "user"

    summary = (
        f"{profile.title()} profile on ${equity:,.0f}: "
        f"Active ${budgets['active']:,.0f} / Options ${budgets['options']:,.0f} / "
        f"Holding ${budgets['holding']:,.0f}."
    )
    return SleevePlan(
        profile=profile, source=source, account_equity=round(equity, 2),
        budgets=budgets, caps={sl: dict(SLEEVE_CAPS[sl]) for sl in SLEEVES},
        summary=summary,
    )


def proven_override_ok(
    edge_entry: Optional[dict],
    *,
    win_rate_bar: float = PROVEN_WIN_RATE,
    min_trades: int = MIN_PROVEN_TRADES,
) -> bool:
    """True when a strategy's REAL logged record clears the proven bar, so an
    over-budget sleeve can wave it through. Fail-safe: missing/thin data ->
    False (no override). `edge_entry` is one value from
    strategy_weighting.get_live_strategy_edge(): {n, win_rate, ...}.
    """
    if not edge_entry:
        return False
    try:
        n = int(edge_entry.get("n") or 0)
        wr = edge_entry.get("win_rate")
        if wr is None:
            return False
        return n >= int(min_trades) and float(wr) >= float(win_rate_bar)
    except (TypeError, ValueError):
        return False


# --- Turnaround / capital velocity (Mike 2026-06-17) -----------------------
# The organizing principle: capital that recycles fast (scalp / ORB, closed the
# same day) is worth more than capital locked for weeks. So a fast trade may
# take a BIGGER bite of its sleeve (it comes back and redeploys), while slow /
# locked trades take small, spread bites. Capacity then scales with the
# account -- a bigger balance simply fits more (and bigger) bites.

TURNAROUND = {
    "crypto_scalp": "fast", "scalp": "fast", "orb": "fast",
    "stms": "intraday", "pattern": "intraday", "crypto_swing": "intraday",
    "long_call": "short", "long_put": "short", "bull_call_spread": "short",
    "bull_put_spread": "short", "iron_condor": "short",
    "cash_secured_put": "short", "iv_crush_short": "short", "extended": "short",
    "wheel_csp": "long", "wheel_cc": "long", "dividend_capture_long": "long",
    "crypto_hodl": "long", "crypto_dca": "long",
}
DEFAULT_TURNAROUND = "intraday"

# Per-trade bite as a fraction of the sleeve budget, by turnaround tier.
SLOT_PCT = {"fast": 0.30, "intraday": 0.20, "short": 0.20, "multiday": 0.12, "long": 0.10}

# Capacity scaling: rough $ of capital per concurrent position. The position
# count the account can hold grows with equity (clamped), so a bigger balance
# works more of the market. The real limit is still the per-sleeve budget.
CAPITAL_PER_SLOT = 500.0
MIN_OPEN_POSITIONS = 4
MAX_OPEN_POSITIONS = 40


def turnaround_for(strategy: str) -> str:
    """Turnaround tier for a strategy (fast / intraday / short / long)."""
    return TURNAROUND.get(_norm(strategy), DEFAULT_TURNAROUND)


def slot_pct_for(strategy: str) -> float:
    """Per-trade bite (fraction of the sleeve budget) for a strategy."""
    return SLOT_PCT.get(turnaround_for(strategy), SLOT_PCT["intraday"])


def scaled_max_open(equity: float) -> int:
    """Account-scaled ceiling on concurrent open positions -- grows with the
    balance so a bigger account works more of the market, clamped to a sane
    band. Wired into the Risk Manager in Part 2b (advisory until then)."""
    try:
        n = round(float(equity or 0) / CAPITAL_PER_SLOT)
    except (TypeError, ValueError):
        n = MIN_OPEN_POSITIONS
    return max(MIN_OPEN_POSITIONS, min(MAX_OPEN_POSITIONS, int(n)))


def compute_slot(
    plan: "SleevePlan",
    sleeve: str,
    deployed: float,
    edge_entry: Optional[dict] = None,
    strategy: str = "",
    *,
    max_breach_mult: float = MAX_BREACH_MULT,
) -> dict:
    """The per-trade capital decision for a sleeve. Pure (no IO).

    Returns a dict with the decision + the max notional the sizer may use:
      decision:
        ok               - room in the sleeve; size up to one slot
        override_proven  - over budget but strategy is proven; allow (<= ceiling)
        hold_over_budget - over budget, not proven; SOFT hold (max_notional 0)
        blocked_ceiling  - proven, but no room left under the breach ceiling
      max_notional: per-trade dollar cap (0.0 means skip / hold)

    max_notional is min(headroom, per_slot) so a single trade can't swallow a
    whole sleeve -- capital spreads across the sleeve's position slots.
    """
    budget = float(plan.budgets.get(sleeve, 0.0))
    # Per-trade bite is velocity-driven: fast turnarounds (scalp/ORB) take a
    # bigger slice (capital returns the same day and redeploys); slow/locked
    # trades take small spread bites. Scales with the sleeve budget (account).
    per_slot = round(budget * slot_pct_for(strategy), 2)
    deployed = max(0.0, float(deployed or 0))
    free = round(budget - deployed, 2)
    ceiling = round(budget * float(max_breach_mult), 2)
    proven = proven_override_ok(edge_entry)

    if free > 0:
        decision, headroom = "ok", free
    elif proven and (ceiling - deployed) > 0:
        decision, headroom = "override_proven", round(ceiling - deployed, 2)
    elif proven:
        decision, headroom = "blocked_ceiling", 0.0
    else:
        decision, headroom = "hold_over_budget", 0.0

    max_notional = round(min(headroom, per_slot), 2) if headroom > 0 else 0.0
    return {
        "sleeve": sleeve,
        "decision": decision,
        "budget": budget,
        "deployed": round(deployed, 2),
        "free": free,
        "per_slot": per_slot,
        "slot_pct": slot_pct_for(strategy),
        "turnaround": turnaround_for(strategy),
        "ceiling": ceiling,
        "headroom": round(headroom, 2),
        "max_notional": max_notional,
        "proven": proven,
        "win_rate": (edge_entry or {}).get("win_rate") if edge_entry else None,
        "n": (edge_entry or {}).get("n") if edge_entry else None,
    }


def _supabase():
    """Service-role Supabase client, or None when unconfigured. Lazy import so
    the module's self-test still runs standalone."""
    try:
        from app.config import get_settings
        s = get_settings()
        if not s.supabase_url or not s.supabase_service_role_key:
            return None
        from supabase import create_client
        return create_client(s.supabase_url, s.supabase_service_role_key)
    except Exception:  # noqa: BLE001
        return None


async def deployed_by_sleeve(user_id: str) -> "dict[str, float]":
    """Sum the notional of this user's OPEN positions, grouped by SLEEVE, so
    the gate knows how much of each sleeve's budget is already in use. Mirrors
    allocation.deployed_capital but buckets by horizon, not market type.
    Fail-safe: returns zeros on any error or when Supabase isn't configured."""
    out = {sl: 0.0 for sl in SLEEVES}
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
        sl = sleeve_for(r.get("strategy") or "", r.get("asset_type") or "")
        out[sl] = out.get(sl, 0.0) + notional
    return out


if __name__ == "__main__":  # pragma: no cover -- self-test / demo
    print("=== Trezo capital sleeves -- self-test ===\n")
    for prof in ("conservative", "balanced", "aggressive"):
        print(build_sleeves(5000, prof).summary)
    print()

    plan = build_sleeves(5000, "balanced")
    print("compute_slot on the Active sleeve ($2,000 budget, 3 slots -> $667/slot):")
    rows = (
        ("empty sleeve",         0.0,    None),
        ("full, proven 78%/12",  2000.0, {"n": 12, "win_rate": 0.78}),
        ("full, weak 60%/12",    2000.0, {"n": 12, "win_rate": 0.60}),
        ("full, thin 90%/3",     2000.0, {"n": 3,  "win_rate": 0.90}),
        ("way over, proven",     3100.0, {"n": 20, "win_rate": 0.80}),
    )
    for label, dep, edge in rows:
        s = compute_slot(plan, "active", dep, edge)
        print(f"  {label:>22}: {s['decision']:<16} max_notional ${s['max_notional']:.0f} "
              f"(free ${s['free']:.0f}, per_slot ${s['per_slot']:.0f}, ceiling ${s['ceiling']:.0f})")

    print("\nCapacity scales with the account (scaled_max_open):")
    for eq in (1000, 5000, 25000, 100000):
        print(f"  ${eq:>7,} -> up to {scaled_max_open(eq)} concurrent positions")

    print("\nVelocity bite per trade (each strategy in its own sleeve, balanced $5k):")
    plan2 = build_sleeves(5000, "balanced")
    for strat, at in (("orb","stock"),("stms","stock"),("extended","stock"),
                      ("long_call","option"),("wheel_csp","option"),("crypto_hodl","crypto")):
        sl = sleeve_for(strat, at)
        sd = compute_slot(plan2, sl, 0.0, None, strat)
        print(f"  {strat:>12} ({turnaround_for(strat):>8}) in {sl:<7} -> bite ${sd['per_slot']:.0f}")

    print("\nsleeve_for() routing spot-check:")
    for strat, at in (("orb", "stock"), ("stms", "stock"), ("extended", "stock"),
                      ("crypto_scalp", "crypto"), ("crypto_hodl", "crypto"),
                      ("long_call", "option"), ("cash_secured_put", "option"),
                      ("wheel_csp", "option"), ("dividend_capture_long", "stock")):
        print(f"  {strat:>22} / {at:<6} -> {sleeve_for(strat, at)}")
