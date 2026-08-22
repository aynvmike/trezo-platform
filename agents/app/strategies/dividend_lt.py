"""Dividends (Long-Term) lane — sizing, graduation, target-return readout.

Implements DIVIDEND_LT_PARAMETERIZED_SPEC.md §1/§2/§3/§5. Pure functions
where possible: every number here is a function of the owner's inputs, so
the lane is capital-agnostic by construction rather than by convention.

The design invariant, from Mike's own book (spec §0): six positions, one
wrapper class, one era — cash yield on cost 17.6% near-uniform, total
return −17.0% to +22.6%. The payout carried NO information about the
outcome.

    This sleeve's job is not a higher mean. It is a narrower spread.

Which is why §5's target-return slider EXPLAINS instead of ACTUATES: a
dial that chases a number would be the same mistake with a nicer UI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# --- §2 calibration constants. Each is a placeholder for a measurement,
# and each is labeled where it came from. Replace with realized numbers
# as the lane accrues data; do NOT quietly tune them to hit a target.
LADDER_YIELD = 0.053        # blended screened bench
LADDER_GROWTH = 0.045       # SCHD-class realized growth, discounted hard
WHEEL_TR = 0.080            # UNPROVEN in this lane until measured (BXM's
                            # 40-yr record says the NET add is low single
                            # digits — treat as optimistic)
BUFFER_YIELD = 0.0375
PREM_RATE_AT_025 = 0.0060   # monthly premium at delta 0.25

# --- §1 guardrails. Hard, not advisory: w_wheel > 40% is not an
# aggression setting, it is a different strategy, and the lane refuses
# rather than silently becoming one.
W_LADDER_RANGE = (0.50, 0.90)
W_WHEEL_RANGE = (0.00, 0.40)
W_BUFFER_RANGE = (0.03, 0.20)
WHEEL_DELTA_RANGE = (0.15, 0.40)     # the ONLY input that changes E[return]
TARGET_RETURN_RANGE = (0.05, 0.25)
MIN_CAPITAL = 500.0
MAX_LADDER_NAMES = 15

# §5 delta reference — UNPROVEN pending live chain data. Replace with
# measured values; the readout must say so until then.
DELTA_TABLE = {
    0.15: {"prem_mo": 0.0040, "blended_tr": 0.084, "assign_prob": 0.15},
    0.20: {"prem_mo": 0.0052, "blended_tr": 0.088, "assign_prob": 0.20},
    0.25: {"prem_mo": 0.0060, "blended_tr": 0.090, "assign_prob": 0.25},
    0.30: {"prem_mo": 0.0075, "blended_tr": 0.095, "assign_prob": 0.30},
    0.40: {"prem_mo": 0.0105, "blended_tr": 0.105, "assign_prob": 0.40},
}


class LaneGuardrailError(ValueError):
    """Raised when an input is outside its hard guardrail. The lane
    refuses rather than clamping silently — a clamp would let the UI
    show one thing while the engine did another."""


@dataclass
class LaneInputs:
    """§1 — what the owner controls. Weights normalize to 100%."""
    capital: float
    contribution_monthly: float = 0.0
    w_ladder: float = 0.70
    w_wheel: float = 0.25
    w_buffer: float = 0.05
    mode: str = "ACCUMULATE"           # ACCUMULATE | INCOME | PARTIAL
    partial_pct: float = 0.0
    wheel_delta: float = 0.25
    target_return: float = 0.12        # display-only — see §5
    block_cost: float = 3500.0         # 100 x cheapest bench price

    def __post_init__(self) -> None:
        if self.capital < MIN_CAPITAL:
            raise LaneGuardrailError(
                f"capital ${self.capital:,.0f} below ${MIN_CAPITAL:,.0f} "
                f"minimum")
        for name, val, rng in (
            ("w_ladder", self.w_ladder, W_LADDER_RANGE),
            ("w_wheel", self.w_wheel, W_WHEEL_RANGE),
            ("w_buffer", self.w_buffer, W_BUFFER_RANGE),
            ("wheel_delta", self.wheel_delta, WHEEL_DELTA_RANGE),
        ):
            if not (rng[0] <= val <= rng[1]):
                raise LaneGuardrailError(
                    f"{name}={val} outside hard guardrail "
                    f"[{rng[0]}, {rng[1]}]")
        if self.mode not in ("ACCUMULATE", "INCOME", "PARTIAL"):
            raise LaneGuardrailError(f"unknown mode '{self.mode}'")

    def normalized(self) -> "LaneInputs":
        """Weights sum to 1.0. Spec: adjust the largest non-touched
        weight — here we scale proportionally, which preserves the
        owner's intended ratios and cannot push a weight out of range."""
        total = self.w_ladder + self.w_wheel + self.w_buffer
        if total <= 0:
            raise LaneGuardrailError("weights sum to zero")
        if abs(total - 1.0) < 1e-9:
            return self
        return LaneInputs(
            capital=self.capital,
            contribution_monthly=self.contribution_monthly,
            w_ladder=self.w_ladder / total,
            w_wheel=self.w_wheel / total,
            w_buffer=self.w_buffer / total,
            mode=self.mode, partial_pct=self.partial_pct,
            wheel_delta=self.wheel_delta, target_return=self.target_return,
            block_cost=self.block_cost,
        )


@dataclass
class LaneSizing:
    """§2 — derived sizing. Pure functions of the inputs."""
    ladder_capital: float
    wheel_capital: float
    buffer_capital: float
    ladder_names: int
    csp_blocks: int
    income_monthly: float
    expected_tr: float
    unlocks: dict = field(default_factory=dict)


def prem_rate_for_delta(delta: float) -> float:
    """Monthly premium rate at a given delta, linearly interpolated
    between the reference points. UNPROVEN — replace with measured."""
    keys = sorted(DELTA_TABLE)
    if delta <= keys[0]:
        return DELTA_TABLE[keys[0]]["prem_mo"]
    if delta >= keys[-1]:
        return DELTA_TABLE[keys[-1]]["prem_mo"]
    for lo, hi in zip(keys, keys[1:]):
        if lo <= delta <= hi:
            span = hi - lo
            w = 0.0 if span == 0 else (delta - lo) / span
            return (DELTA_TABLE[lo]["prem_mo"] * (1 - w)
                    + DELTA_TABLE[hi]["prem_mo"] * w)
    return PREM_RATE_AT_025


def size_lane(inp: LaneInputs) -> LaneSizing:
    """§2 derived sizing, plus §3 book-level unlocks.

    Expected TR is FLAT across capital, and that is correct and
    important: size buys mechanics, not edge. Anything in the UI
    implying bigger = better-returning is a bug.
    """
    i = inp.normalized()
    L = i.capital * i.w_ladder
    W = i.capital * i.w_wheel
    B = i.capital * i.w_buffer

    ladder_names = max(1, min(MAX_LADDER_NAMES, int(L // 1000)))
    csp_blocks = int(W // i.block_cost) if i.block_cost > 0 else 0

    prem_rate = prem_rate_for_delta(i.wheel_delta)
    income_monthly = (
        L * LADDER_YIELD / 12.0
        + csp_blocks * i.block_cost * prem_rate
        + B * BUFFER_YIELD / 12.0
    )
    expected_tr = (
        i.w_ladder * (LADDER_YIELD + LADDER_GROWTH)
        + i.w_wheel * WHEEL_TR
        + i.w_buffer * BUFFER_YIELD
    )

    # §3 book-level unlocks
    unlocks = {
        "U1_wheel": W >= i.block_cost,
        "U2_multi_csp": csp_blocks >= 2,
        "U3_diversification": ladder_names >= 12,
        "U4_selectivity": i.capital >= 50_000,
    }
    return LaneSizing(
        ladder_capital=L, wheel_capital=W, buffer_capital=B,
        ladder_names=ladder_names, csp_blocks=csp_blocks,
        income_monthly=income_monthly, expected_tr=expected_tr,
        unlocks=unlocks,
    )


def per_name_cap_pct(sizing: LaneSizing) -> float:
    """§3 U3: below 12 ladder names the concentration cap is the binding
    risk control and must be ENFORCED, not warned. 20% until U3, then
    it relaxes to 10%."""
    return 0.10 if sizing.unlocks.get("U3_diversification") else 0.20


# --- §3 per-name state machine -------------------------------------------

FRACTIONAL = "FRACTIONAL"
LOT_READY = "LOT_READY"
LOT_HELD = "LOT_HELD"
CASH_SECURED = "CASH_SECURED"
ASSIGNED = "ASSIGNED"

VALID_STATES = (FRACTIONAL, LOT_READY, LOT_HELD, CASH_SECURED, ASSIGNED)


def name_state(shares: float, tier: str, *,
               cash_reserved_for_csp: bool = False,
               came_from_assignment: bool = False) -> str:
    """Which state a name is in. Exactly one, always.

    The tier split is lane rule #4 made structural: a GROWTH name with a
    round lot is LOT_HELD, not LOT_READY, so no covered-call path can
    ever select it. Writing calls on the compounders sells the 4-6%/yr
    payout growth that justified owning them — the capture-asymmetry
    mistake from the YieldMax study.
    """
    if cash_reserved_for_csp and shares <= 0:
        return CASH_SECURED
    if came_from_assignment and shares >= 100:
        return ASSIGNED
    if shares < 100:
        return FRACTIONAL
    return LOT_READY if str(tier).upper() == "HIGH_YIELD" else LOT_HELD


def can_write_covered_call(state: str, tier: str) -> tuple:
    """Lane rule #4, enforced. Returns (allowed, reason)."""
    t = str(tier).upper()
    if t == "GROWTH":
        return False, ("GROWTH tier never writes calls — that sells the "
                       "payout growth that justified owning it")
    if state == FRACTIONAL:
        return False, ("under 100 shares — dividend-only until it "
                       "graduates (lane rule #2)")
    if state not in (LOT_READY, ASSIGNED):
        return False, f"state {state} is not call-eligible"
    if t != "HIGH_YIELD":
        return False, f"tier {t or 'UNVERIFIED'} is not wheel-eligible"
    return True, "eligible"


# --- §5 the target-return readout ----------------------------------------

@dataclass
class TargetReadout:
    """§5 — the one novel object. Wired to EXPLAIN, not to actuate.

    Moving the target changes no order, no strike, no allocation. It
    prints the requirement, and it names which of two very different
    animals you would be choosing.
    """
    target_return: float
    expected_tr: float
    gap: float
    appreciation_required: Optional[float]
    premium_required: Optional[float]
    implied_delta: Optional[float]
    reachable: bool
    blocking_rule: Optional[str]
    note: str


def _delta_for_prem(prem_mo: float) -> Optional[float]:
    """Invert the delta table: what delta would this monthly premium
    imply? Returns None above the table (i.e. off the guardrail)."""
    keys = sorted(DELTA_TABLE)
    if prem_mo <= DELTA_TABLE[keys[0]]["prem_mo"]:
        return keys[0]
    for lo, hi in zip(keys, keys[1:]):
        p_lo = DELTA_TABLE[lo]["prem_mo"]
        p_hi = DELTA_TABLE[hi]["prem_mo"]
        if p_lo <= prem_mo <= p_hi:
            span = p_hi - p_lo
            w = 0.0 if span == 0 else (prem_mo - p_lo) / span
            return lo + (hi - lo) * w
    return None


def target_readout(inp: LaneInputs, sizing: LaneSizing,
                   target_return: Optional[float] = None) -> TargetReadout:
    """Compute what a target WOULD require. Never changes anything."""
    i = inp.normalized()
    target = i.target_return if target_return is None else target_return
    if not (TARGET_RETURN_RANGE[0] <= target <= TARGET_RETURN_RANGE[1]):
        raise LaneGuardrailError(
            f"target_return {target} outside "
            f"[{TARGET_RETURN_RANGE[0]}, {TARGET_RETURN_RANGE[1]}]")

    gap = target - sizing.expected_tr
    appreciation_required = (
        LADDER_GROWTH + gap / i.w_ladder if i.w_ladder > 0 else None)
    premium_required = (
        PREM_RATE_AT_025 + gap / i.w_wheel / 12.0 if i.w_wheel > 0 else None)

    implied_delta = (_delta_for_prem(premium_required)
                     if premium_required is not None else None)

    reachable = True
    blocking_rule = None
    if premium_required is None:
        # No wheel allocation — the premium path does not exist at all.
        pass
    elif implied_delta is None or implied_delta > WHEEL_DELTA_RANGE[1]:
        reachable = False
        blocking_rule = (
            f"wheel_delta hard cap {WHEEL_DELTA_RANGE[1]} (§1 input #7)")

    if not reachable and (appreciation_required is None
                          or appreciation_required > 0.25):
        note = ("unreachable within lane guardrails — "
                f"blocked by {blocking_rule}")
    elif not reachable:
        note = (f"the premium path is unreachable within lane guardrails "
                f"(blocked by {blocking_rule}); the appreciation path "
                f"remains open at {appreciation_required*100:.1f}%/yr")
    else:
        note = ("appreciation is a market outcome you wait for; premium "
                "is a setting you choose. Same number, two different "
                "animals — one is patience, one is leverage on conviction")

    return TargetReadout(
        target_return=target, expected_tr=sizing.expected_tr, gap=gap,
        appreciation_required=appreciation_required,
        premium_required=premium_required, implied_delta=implied_delta,
        reachable=reachable, blocking_rule=blocking_rule, note=note,
    )


def project(inp: LaneInputs, years: int = 5,
            annual_return: Optional[float] = None) -> dict:
    """§6 — what the lane honestly produces. Monthly compounding with
    contributions.

    The contribution row dwarfing the return row held in every projection
    run this cycle. That is the finding, not a footnote.
    """
    i = inp.normalized()
    r = annual_return if annual_return is not None else size_lane(i).expected_tr
    monthly_r = (1 + r) ** (1 / 12.0) - 1
    balance = i.capital
    contributed = 0.0
    for _ in range(years * 12):
        balance = balance * (1 + monthly_r) + i.contribution_monthly
        contributed += i.contribution_monthly
    return {
        "years": years,
        "annual_return_used": r,
        "ending_balance": balance,
        "starting_capital": i.capital,
        "total_contributed": contributed,
        "growth": balance - i.capital - contributed,
        # The comparison the spec insists on surfacing:
        "contribution_vs_growth": (
            "contributions exceed investment growth"
            if contributed > (balance - i.capital - contributed)
            else "investment growth exceeds contributions"),
    }


def income_draw(inp: LaneInputs, actual_distributions: float,
                trailing_12mo_total_return: float) -> float:
    """§6 INCOME mode: draw = min(actual distributions, 90% of trailing
    12-month total return). Shortfalls come from the buffer; excess
    auto-reinvests. Never draws from principal by construction."""
    ceiling = max(0.0, 0.90 * trailing_12mo_total_return)
    return max(0.0, min(actual_distributions, ceiling))
