"""Wheel Advisor — an advisory gate at the END of the wheel path.

Mike 2026-08-23: "no need to remove the wheel from it, but what if we
have a gate for an agent at the end of it that helps with the wheel
schedules and strategies... we are adding a variable so it should be able
to work with the system and not have to change it all the way."

That is the right shape, and it is worth being explicit about why.
options_scanner.py is 2,753 lines with wheel logic threaded through its
cooldowns, Greek filters, allocation buckets and OCC matching. It works.
Rewriting a working thing to add a rule is how working things stop
working. So this module does not touch the wheel's decisions — it sits at
the end of them and answers one question:

    "Given everything the Wheel just decided, should this leg go now?"

DESIGN RULES, in order of importance:

1. IT FAILS OPEN. Any exception, any missing data, any disabled flag —
   the answer is ALLOW. A new advisory component must never be able to
   freeze a lane that was working before it existed. Every code path
   below either returns an explicit verdict or falls through to allow.

2. IT ONLY SUBTRACTS. The advisor can defer a leg or shrink it. It can
   never invent a leg, raise size, pick a different strike, or widen a
   window. Anything that could ADD exposure stays with the Wheel.

3. ITS REASONS ARE READABLE. Every deferral names the rule and what would
   clear it, because a silent "no" from a component nobody can see is
   worse than the trade it prevented.

WHAT IT ENFORCES — the dividend lane's rules, applied to wheel legs
without the Wheel having to know they exist:
  - Ex-date guard (spec §4 rule 3): never carry an ITM short call into
    an ex-date. Early exercise takes the dividend with it.
  - GROWTH tier never wears a call (spec §4 rule 4): writing calls on a
    compounder sells the payout growth that justified owning it.
  - Collateral honesty (spec §4 rule 5): a CSP's cash is reserved, and
    reserved cash cannot back a second obligation.
  - Schedule: DTE window and earnings proximity — the two timing
    mistakes that turn a premium plan into a directional bet.
"""

from __future__ import annotations

import datetime as _dt
import os
from dataclasses import dataclass, field
from typing import Optional

import structlog

log = structlog.get_logger("trezo.wheel_advisor")

# The single variable that turns the whole gate on or off. Default ON,
# but one env change disables it entirely and the Wheel reverts to
# exactly its previous behavior — no code path removed, none rerouted.
ENV_FLAG = "TREZO_WHEEL_ADVISOR"

# Schedule windows. Deliberately wide: this gate exists to catch the
# clearly-wrong, not to micro-manage strike selection.
MIN_DTE = 5
MAX_DTE = 45
EARNINGS_BLACKOUT_DAYS = 2      # do not open a new leg across earnings


def advisor_enabled() -> bool:
    return os.getenv(ENV_FLAG, "1") not in ("0", "false", "False", "off")


@dataclass
class WheelVerdict:
    """allow=True means 'the Wheel's own decision stands'."""
    allow: bool = True
    reason: str = "advisor: no objection"
    rule: Optional[str] = None          # which rule fired
    clears_when: Optional[str] = None   # what would make this pass
    max_contracts: Optional[int] = None  # advisory shrink, never a raise
    notes: list = field(default_factory=list)

    def as_block_payload(self, underlying: str, strategy: str) -> dict:
        """Shaped like options_scanner's existing wheel_auto_blocked
        payload, so nothing downstream has to learn a new format."""
        return {
            "event": "wheel_auto_blocked",
            "underlying": underlying,
            "strategy": strategy,
            "reason": f"[advisor/{self.rule}] {self.reason}",
            "clears_when": self.clears_when,
            "advisor": True,
        }


def _allow(reason: str = "advisor: no objection") -> WheelVerdict:
    return WheelVerdict(allow=True, reason=reason)


def _defer(rule: str, reason: str, clears_when: str) -> WheelVerdict:
    return WheelVerdict(allow=False, reason=reason, rule=rule,
                        clears_when=clears_when)


def check_schedule(expiration: str,
                   next_earnings: Optional[str] = None) -> WheelVerdict:
    """DTE window + earnings proximity. The two timing mistakes that turn
    a premium plan into a directional bet: too short to collect decay,
    too long to stay liquid, or straddling an earnings print."""
    try:
        exp = _dt.date.fromisoformat(str(expiration)[:10])
    except (TypeError, ValueError):
        return _allow("advisor: unparseable expiration, deferring to Wheel")

    today = _dt.datetime.now(_dt.timezone.utc).date()
    dte = (exp - today).days

    if dte < MIN_DTE:
        return _defer(
            "schedule.dte_floor",
            f"{dte} DTE is inside the {MIN_DTE}-day floor — gamma is "
            f"steep here and there is little premium left to collect",
            f"an expiration {MIN_DTE}+ days out")
    if dte > MAX_DTE:
        return _defer(
            "schedule.dte_ceiling",
            f"{dte} DTE is past the {MAX_DTE}-day ceiling — capital sits "
            f"reserved far longer than the premium justifies",
            f"an expiration within {MAX_DTE} days")

    if next_earnings:
        try:
            earn = _dt.date.fromisoformat(str(next_earnings)[:10])
            days_to_earn = (earn - today).days
            if 0 <= days_to_earn <= EARNINGS_BLACKOUT_DAYS:
                return _defer(
                    "schedule.earnings_blackout",
                    f"earnings in {days_to_earn}d — opening a new leg "
                    f"across the print is a volatility bet, not a "
                    f"premium plan",
                    f"after the {earn} print, or an expiration that "
                    f"clears it")
            if earn <= exp and days_to_earn >= 0:
                return WheelVerdict(
                    allow=True,
                    reason=(f"advisor: allowed, but this leg spans the "
                            f"{earn} earnings print"),
                    notes=[f"earnings {earn} falls before expiry {exp}"])
        except (TypeError, ValueError):
            pass

    return _allow(f"advisor: {dte} DTE inside the window")


def check_tier(strategy: str, tier: Optional[str]) -> WheelVerdict:
    """Lane rule #4, applied to the wheel path.

    Only covered calls are gated. A CSP on a GROWTH name is fine — that
    is how you ACQUIRE a compounder at a discount. It is writing calls on
    one, capping the upside you bought it for, that the rule forbids.

    An UNKNOWN tier allows. The screen ratchets over time and a name it
    has not reached yet must not be blocked by that silence — the
    advisor's job is to catch the clearly-wrong, not to gate on absence.
    """
    if strategy != "wheel_cc":
        return _allow("advisor: tier rule applies to covered calls only")
    t = (tier or "UNKNOWN").upper()
    if t == "GROWTH":
        return _defer(
            "lane_rule_4.growth_no_calls",
            "GROWTH tier: writing a call here sells the 4-6%/yr payout "
            "growth that justified holding it — the capture-asymmetry "
            "mistake from the YieldMax study",
            "the name re-tiering to HIGH_YIELD, or the call being written "
            "on a different holding")
    return _allow(f"advisor: tier {t} may wear a call")


def check_ex_date(*, strategy: str, strike: float, spot: float,
                  expiration: str, ex_date: Optional[str],
                  remaining_time_value: Optional[float] = None,
                  dividend_amount: Optional[float] = None) -> WheelVerdict:
    """Lane rule #3, applied to the wheel path. Only covered calls can
    lose a dividend to early exercise; a short put cannot."""
    if strategy != "wheel_cc":
        return _allow("advisor: ex-date rule applies to covered calls only")
    try:
        from app.strategies.dividend_lane_rules import ex_date_guard
    except Exception:  # noqa: BLE001
        return _allow("advisor: lane rules unavailable — deferring to Wheel")

    v = ex_date_guard(strike=strike, spot=spot, expiration=expiration,
                      ex_date=ex_date,
                      remaining_time_value=remaining_time_value,
                      dividend_amount=dividend_amount)
    if v.allowed:
        return _allow(f"advisor: ex-date clear ({v.reason})")
    return _defer(
        "lane_rule_3.ex_date_guard", v.reason,
        "an expiration that clears the ex-date, or an OTM buffer")


def check_collateral(*, strategy: str, strike: float, contracts: int,
                     lane_cash: Optional[float],
                     reserved_for_open_csps: Optional[float]
                     ) -> WheelVerdict:
    """Lane rule #5, applied to the wheel path. Advisory only: the Wheel
    already has its own buying-power gate against the BROKER. This one
    asks the different question of whether the LEDGER can honestly back
    it once existing CSP reservations are subtracted."""
    if strategy != "wheel_csp":
        return _allow("advisor: collateral rule applies to CSPs only")
    if lane_cash is None or reserved_for_open_csps is None:
        return _allow("advisor: ledger cash unknown — deferring to Wheel")
    try:
        from app.strategies.dividend_lane_rules import (
            check_collateral as _cc)
    except Exception:  # noqa: BLE001
        return _allow("advisor: lane rules unavailable — deferring to Wheel")

    c = _cc(strike=strike, contracts=contracts, lane_cash=lane_cash,
            reserved_for_open_csps=reserved_for_open_csps)
    if c.ok:
        return _allow(f"advisor: collateral honest ({c.reason})")
    return _defer("lane_rule_5.collateral", c.reason,
                  "an existing CSP closing, or fewer contracts")


async def advise_wheel_leg(*, user_id: str, underlying: str, strategy: str,
                           strike: float, expiration: str,
                           contracts: int = 1,
                           spot: Optional[float] = None,
                           tier: Optional[str] = None,
                           ex_date: Optional[str] = None,
                           next_earnings: Optional[str] = None,
                           lane_cash: Optional[float] = None,
                           reserved_for_open_csps: Optional[float] = None,
                           ) -> WheelVerdict:
    """THE GATE. One call, one verdict, always safe to ignore.

    Called by options_scanner at the end of its wheel path, after it has
    already decided everything. Returns allow=True unless a named rule
    fires. Wrapped so that ANY failure allows: this component must never
    be the reason a working lane stops.
    """
    if not advisor_enabled():
        return _allow(f"advisor: disabled via {ENV_FLAG}")

    try:
        checks = [
            check_schedule(expiration, next_earnings),
            check_tier(strategy, tier),
            check_collateral(strategy=strategy, strike=strike,
                             contracts=contracts, lane_cash=lane_cash,
                             reserved_for_open_csps=reserved_for_open_csps),
        ]
        if spot is not None:
            checks.append(check_ex_date(
                strategy=strategy, strike=strike, spot=spot,
                expiration=expiration, ex_date=ex_date))

        for v in checks:
            if not v.allow:
                log.info("wheel_advisor.deferred", user_id=str(user_id)[:8],
                         underlying=underlying, strategy=strategy,
                         rule=v.rule, reason=v.reason[:160])
                return v

        notes = [n for v in checks for n in v.notes]
        return WheelVerdict(allow=True, reason="advisor: no objection",
                            notes=notes)
    except Exception as e:  # noqa: BLE001
        # FAIL OPEN, loudly. A broken advisor is a logging problem, never
        # a trading one.
        log.warning("wheel_advisor.failed_open", underlying=underlying,
                    error=str(e)[:200])
        return _allow(f"advisor: failed open ({str(e)[:80]})")
