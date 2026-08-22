"""Lane rules 1, 3 and 5 — the ones that need runtime state, not just math.

Rules 2 and 4 (graduation at 100 shares, GROWTH tier never writes calls)
live in `dividend_lt.name_state` / `can_write_covered_call` because they
are pure functions of a position. The three here touch the broker, the
calendar, or the cash ledger.

  1. Two-state names        — a wheel name is EITHER cash securing a put
                              OR shares wearing a call. Sequential,
                              never simultaneous.
  3. Ex-date guard          — never carry an ITM short call into an
                              ex-date.
  5. Hard collateral        — CSP collateral is reserved cash and cannot
                              double-count as ladder capital.

Rule 5 is flagged in the spec as the same defect family as the primary
book's options-BP accounting bug: ship the reservation BEFORE the first
CSP, not after the first surprise.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Optional

import structlog

log = structlog.get_logger("trezo.dividend_lane_rules")


# --- Rule 3: the ex-date guard -------------------------------------------

@dataclass
class ExDateVerdict:
    allowed: bool
    reason: str
    ex_date: Optional[str] = None
    days_to_ex: Optional[int] = None


def ex_date_guard(*, strike: float, spot: float, expiration: str,
                  ex_date: Optional[str],
                  remaining_time_value: Optional[float] = None,
                  dividend_amount: Optional[float] = None) -> ExDateVerdict:
    """May this short call be opened or carried?

    THE MECHANIC (spec §4 rule 3): an ITM short call whose remaining TIME
    VALUE is below the upcoming dividend gets exercised early — the
    counterparty takes the shares AND the dividend. The lane loses the
    payout that was the entire reason for holding the name.

    The rule: expiration clears the ex-date, or maintain an OTM buffer.

    Passing `remaining_time_value` and `dividend_amount` sharpens the
    call from "is it ITM" to the actual early-exercise condition. Without
    them we fall back to the conservative structural test.
    """
    if not ex_date:
        return ExDateVerdict(True, "no ex-date on file for this name")

    try:
        ex = _dt.date.fromisoformat(str(ex_date)[:10])
        exp = _dt.date.fromisoformat(str(expiration)[:10])
    except (TypeError, ValueError):
        return ExDateVerdict(True, "unparseable dates — guard not applied")

    today = _dt.datetime.now(_dt.timezone.utc).date()
    days_to_ex = (ex - today).days

    # Expiration clears the ex-date: the contract is gone before the
    # dividend is ever at risk. This is the clean path.
    if exp < ex:
        return ExDateVerdict(
            True, "expiration clears the ex-date", str(ex), days_to_ex)

    # Ex-date already passed for this cycle.
    if days_to_ex < 0:
        return ExDateVerdict(
            True, "ex-date already passed", str(ex), days_to_ex)

    itm = spot > strike
    if not itm:
        # OTM buffer maintained — the second permitted path. We still
        # report how thin the buffer is so the caller can size sensibly.
        buffer_pct = (strike - spot) / spot if spot > 0 else 0.0
        if buffer_pct < 0.01:
            return ExDateVerdict(
                False,
                f"only {buffer_pct*100:.1f}% OTM with ex-date in "
                f"{days_to_ex}d — buffer too thin to survive a move",
                str(ex), days_to_ex)
        return ExDateVerdict(
            True, f"OTM buffer {buffer_pct*100:.1f}% holds through ex-date",
            str(ex), days_to_ex)

    # ITM and the contract lives past the ex-date. If we know the numbers,
    # apply the real early-exercise test.
    if remaining_time_value is not None and dividend_amount is not None:
        if remaining_time_value > dividend_amount:
            return ExDateVerdict(
                True,
                f"ITM but time value ${remaining_time_value:.2f} exceeds "
                f"dividend ${dividend_amount:.2f} — early exercise "
                f"irrational",
                str(ex), days_to_ex)
        return ExDateVerdict(
            False,
            f"ITM with time value ${remaining_time_value:.2f} below "
            f"dividend ${dividend_amount:.2f} — early exercise takes the "
            f"dividend",
            str(ex), days_to_ex)

    return ExDateVerdict(
        False,
        f"ITM short call carried into ex-date in {days_to_ex}d — "
        f"roll out past {ex}, or close",
        str(ex), days_to_ex)


# --- Rule 5: hard collateral reservation ---------------------------------

@dataclass
class CollateralCheck:
    ok: bool
    reason: str
    required: float = 0.0
    available: float = 0.0
    already_reserved: float = 0.0


def csp_collateral_required(strike: float, contracts: int = 1) -> float:
    """Cash-secured means cash-secured: strike x 100 x contracts."""
    return max(0.0, float(strike) * 100.0 * max(1, int(contracts)))


def check_collateral(*, strike: float, contracts: int,
                     lane_cash: float, reserved_for_open_csps: float,
                     ladder_capital_committed: float = 0.0
                     ) -> CollateralCheck:
    """Can this CSP be opened without double-counting ladder capital?

    The defect this prevents: counting the same dollar as both ladder
    capital and CSP collateral, so the book believes it has more room
    than it has. Same family as the options-BP accounting bug on the
    primary book. Collateral already committed to OPEN CSPs is subtracted
    before the question is even asked.
    """
    required = csp_collateral_required(strike, contracts)
    free = lane_cash - reserved_for_open_csps
    if free < 0:
        return CollateralCheck(
            False,
            f"ledger inconsistent: ${reserved_for_open_csps:,.0f} reserved "
            f"exceeds ${lane_cash:,.0f} lane cash — reconcile before "
            f"writing",
            required, free, reserved_for_open_csps)
    if required > free:
        return CollateralCheck(
            False,
            f"needs ${required:,.0f} collateral, only ${free:,.0f} free "
            f"(${reserved_for_open_csps:,.0f} already securing open CSPs)",
            required, free, reserved_for_open_csps)
    return CollateralCheck(
        True,
        f"${required:,.0f} reserved from ${free:,.0f} free lane cash",
        required, free, reserved_for_open_csps)


# --- Rule 1: two-state names ---------------------------------------------

def two_state_check(*, ticker: str, has_open_csp: bool,
                    has_open_covered_call: bool,
                    shares: float) -> tuple:
    """A wheel name earns in exactly one state at a time.

    Returns (ok, reason). Simultaneous put-and-call on the same name is
    not a straddle the lane intends — it is an accounting collision where
    the same capital appears to back two obligations.
    """
    if has_open_csp and has_open_covered_call:
        return False, (f"{ticker} has BOTH an open CSP and an open covered "
                       f"call — rule 1 says sequential, never simultaneous")
    if has_open_csp and shares >= 100:
        return False, (f"{ticker} holds {shares:.0f} shares AND an open "
                       f"CSP — securing a put on a name already owned "
                       f"double-books the lane's capital")
    return True, "single state"
