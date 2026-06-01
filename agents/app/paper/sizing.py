"""Account-aware position sizing.

Phase 8a. Sizes every trade off *current account equity*, so the same
rules produce a small position on a $10k account and a proportionally
larger one on a $100k account — the dollar range scales with the
account, the risk percentage stays constant.

Implements the sizing rules from TREZO_NOVA_BOT_TRADE_RULES.md sections
4-5, with one Trezo override: the user's Bot Tuning risk slider is
authoritative. The document's 0.5-1% testing band and 2% ceiling are
defaults — whatever the user sets on the slider (up to its own 25% max)
is what the engine uses. The risk slider is the single risk control;
the only hard limit above it is available buying power.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional


# --- Guardrails -------------------------------------------------------
DEFAULT_RISK_PCT = 0.01    # 1% per trade — the document's testing target
DOC_RISK_CEILING = 0.02    # 2% — the document's hard ceiling (a default)
SLIDER_RISK_MAX = 0.25     # the Bot Tuning slider's own maximum
SLIDER_RISK_MIN = 0.0005   # floor so a zero slider can't divide trades to nothing
# A single position may use up to 100% of equity — i.e. it is bounded by
# buying power, not by an artificial concentration cap. The risk slider
# is what controls risk; this stays at 1.0 so the slider truly governs.
NOTIONAL_CAP_PCT = 1.0
MIN_REWARD_RISK = 1.5      # SEED — overridden per-user by bot_settings.min_reward_risk.
                            # The user's risk profile (conservative / balanced / aggressive /
                            # expert) drives this. Range enforced 0.3-3.0 in the form layer.


def account_tier(equity: float) -> str:
    """Classify an account by size. Drives display and day-trade context —
    accounts under $25k are pattern-day-trader restricted."""
    if equity < 2_000:
        return "micro"
    if equity < 25_000:
        return "small"
    if equity < 100_000:
        return "standard"
    return "large"


@dataclass
class SizingPlan:
    ok: bool
    quantity: float = 0.0
    notional_usd: float = 0.0
    risk_usd: float = 0.0
    risk_pct: float = 0.0          # effective risk as a share of equity
    stop_distance: float = 0.0
    reward_risk: float = 0.0
    account_equity: float = 0.0
    account_tier: str = "micro"
    capped: bool = False           # True if buying power limited the size
    reject_reason: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def plan_position(
    equity: float,
    entry_price: float,
    stop_price: float,
    target_price: Optional[float] = None,
    risk_pct: Optional[float] = None,
    asset_type: str = "stock",
    buying_power: Optional[float] = None,
) -> SizingPlan:
    """Build a defined-risk position plan, sized off current account equity.

    `risk_pct` is the user's Bot Tuning slider value and is authoritative —
    it can exceed the document's conservative band. None falls back to the
    document default. The position is the risk-based size unless that would
    need more buying power than the account has, in which case it is capped
    (and `capped` is set so the caller can see the dialed risk was limited).
    """
    tier = account_tier(max(0.0, equity))

    if equity <= 0:
        return SizingPlan(ok=False, account_equity=equity, account_tier=tier,
                          reject_reason="Account equity is zero - cannot size a trade")
    if entry_price <= 0 or stop_price <= 0:
        return SizingPlan(ok=False, account_equity=equity, account_tier=tier,
                          reject_reason="Missing or invalid entry/stop price")

    stop_distance = abs(entry_price - stop_price)
    if stop_distance <= 0:
        return SizingPlan(ok=False, account_equity=equity, account_tier=tier,
                          reject_reason="Stop distance is zero - no defined risk")

    # The slider overpowers the document's risk numbers.
    eff_risk = DEFAULT_RISK_PCT if risk_pct is None else risk_pct
    eff_risk = _clamp(eff_risk, SLIDER_RISK_MIN, SLIDER_RISK_MAX)

    # Risk-based size: this delivers exactly the dialed risk and scales
    # one-to-one with account equity.
    risk_usd = equity * eff_risk
    risk_qty = risk_usd / stop_distance

    # The only ceiling above the risk slider is buying power.
    notional_cap = equity * NOTIONAL_CAP_PCT
    if buying_power is not None and buying_power > 0:
        notional_cap = min(notional_cap, buying_power)

    qty = risk_qty
    capped = False
    if qty * entry_price > notional_cap:
        qty = notional_cap / entry_price
        capped = True

    if asset_type != "crypto":
        qty = float(int(qty))   # whole shares only
        if qty < 1:
            return SizingPlan(
                ok=False, account_equity=equity, account_tier=tier,
                stop_distance=round(stop_distance, 4),
                reject_reason=(
                    f"Sizing produced 0 shares. equity=${equity:.0f}, "
                    f"risk={eff_risk * 100:.2f}% (${risk_usd:.2f}), "
                    f"stop=${stop_distance:.2f}, entry=${entry_price:.2f}, "
                    f"notional_cap=${notional_cap:.0f}. Either raise Risk per "
                    f"trade in Bot Tuning, tighten the stop, or check if your "
                    f"market-type budget is full (Bot Tuning · Account Posture)."
                )
            )
    elif qty <= 0:
        return SizingPlan(ok=False, account_equity=equity, account_tier=tier,
                          stop_distance=round(stop_distance, 4),
                          reject_reason="Computed quantity rounds to zero")

    notional = qty * entry_price
    actual_risk = qty * stop_distance

    reward_risk = 0.0
    if target_price and target_price > 0:
        reward = abs(target_price - entry_price)
        reward_risk = round(reward / stop_distance, 2)
        # Per-user floor from Bot Tuning. Falls back to the seed (1.5)
        # if the settings module isn't reachable.
        try:
            from app.runtime.settings import get_bot_settings as _gbs
            floor = float(_gbs().min_reward_risk or MIN_REWARD_RISK)
        except Exception:  # noqa: BLE001
            floor = MIN_REWARD_RISK
        # Clamp to a sane band so a typo can't disable the floor entirely.
        floor = max(0.3, min(3.0, floor))
        if reward_risk < floor:
            return SizingPlan(ok=False, account_equity=equity, account_tier=tier,
                              stop_distance=round(stop_distance, 4), reward_risk=reward_risk,
                              reject_reason=f"Reward:risk {reward_risk} below your {floor} floor — raise the profit target, tighten the stop, or lower the R:R floor in Bot Tuning.")

    return SizingPlan(
        ok=True,
        quantity=qty,
        notional_usd=round(notional, 2),
        risk_usd=round(actual_risk, 2),
        risk_pct=round(actual_risk / equity, 4),
        stop_distance=round(stop_distance, 4),
        reward_risk=reward_risk,
        account_equity=round(equity, 2),
        account_tier=tier,
        capped=capped,
    )
