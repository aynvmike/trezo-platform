"""Offline income arithmetic; never a strategy forecast or a broker action.

Run from agents/: python -m app.paper.income_planner
The default report has $1,000/$5,000 starting cases and $20,000/$40,000
annual income goals. Return scenarios are OPTIONAL and explicitly supplied.

This one-year comparison credits optional deposits at year-end, after
investment returns. It assumes a return after variable trading costs but
before the separately supplied fixed annual cost and personal taxes. The
illustrative withdrawal is capped at positive net gains, assumes those
gains can be realized as cash, and includes no tax/reserve provision.
It is not an eligibility decision for an actual account. No config, data,
ledger, agent, credential, or broker module is imported.
"""

from __future__ import annotations

import argparse
import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


STARTING_BALANCES = ("1000", "5000")
ANNUAL_INCOME_GOALS = ("20000", "40000")
CENT = Decimal("0.01")
ZERO = Decimal("0")
HUNDRED = Decimal("100")


def _number(value, field: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a finite number")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{field} must be a finite number") from exc
    if not result.is_finite():
        raise ValueError(f"{field} must be a finite number")
    return result


def _amount(value, field: str, *, positive: bool = False) -> Decimal:
    result = _number(value, field)
    if result < 0 or (positive and result == 0):
        raise ValueError(f"{field} must be {'positive' if positive else 'nonnegative'}")
    try:
        cents = result.quantize(CENT)
    except InvalidOperation as exc:
        raise ValueError(f"{field} is outside the supported numeric precision") from exc
    if result != cents:
        raise ValueError(f"{field} must be specified in whole cents")
    return cents


def _money(value: Decimal) -> str:
    return format(value.quantize(CENT, rounding=ROUND_HALF_UP), ".2f")


def goal_requirement(starting_balance, annual_income_goal,
                     fixed_annual_cost="0") -> dict:
    """Return needed for one year's income while retaining opening capital.

    This is a required-return calculation, not an estimated return. End-of-
    year deposits cannot reduce it because they earn no return in this model.
    """
    start = _amount(starting_balance, "starting_balance", positive=True)
    goal = _amount(annual_income_goal, "annual_income_goal")
    cost = _amount(fixed_annual_cost, "fixed_annual_cost")
    required_pct = (goal + cost) / start * HUNDRED
    return {
        "starting_balance": _money(start),
        "annual_income_goal": _money(goal),
        "fixed_annual_cost": _money(cost),
        "required_trading_return_pct": format(required_pct.quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP), ".4f"),
    }


def project_first_year(starting_balance, assumed_trading_return_pct,
                       annual_income_goal="0", fixed_annual_cost="0",
                       year_end_deposit="0") -> dict:
    """Illustrate one supplied return; payouts never come from deposits.

    Money is rounded to cents once when the modeled trading result is
    booked. A cost shortfall remains negative net equity with an explicit
    funding shortfall; the planner does not invent a deposit to cover it.
    """
    start = _amount(starting_balance, "starting_balance", positive=True)
    goal = _amount(annual_income_goal, "annual_income_goal")
    cost = _amount(fixed_annual_cost, "fixed_annual_cost")
    deposit = _amount(year_end_deposit, "year_end_deposit")
    rate = _number(assumed_trading_return_pct, "assumed_trading_return_pct")
    if rate < -HUNDRED:
        raise ValueError("This planner models returns no lower than -100%; "
                         "it does not model leveraged trading liabilities")

    trading_result = (start * rate / HUNDRED).quantize(
        CENT, rounding=ROUND_HALF_UP)
    net_profit = trading_result - cost
    before_withdrawal = start + deposit + net_profit
    payout = min(goal, max(ZERO, net_profit))
    remaining = before_withdrawal - payout

    return {
        "starting_balance": _money(start),
        "assumed_trading_return_pct": format(rate, "f"),
        "annual_income_goal": _money(goal),
        "trading_result_before_fixed_cost": _money(trading_result),
        "fixed_annual_cost": _money(cost),
        "net_profit_before_personal_taxes": _money(net_profit),
        "year_end_deposit": _money(deposit),
        "equity_before_withdrawal": _money(before_withdrawal),
        "illustrative_profit_only_withdrawal": _money(payout),
        "unmet_income_goal": _money(goal - payout),
        "income_goal_met": payout == goal if goal > 0 else None,
        "remaining_net_equity": _money(remaining),
        "additional_cash_required_for_unfunded_costs": _money(max(ZERO, -remaining)),
    }


def build_report(*, starting_balances=None, annual_income_goals=None,
                 annual_returns_pct=None, fixed_annual_cost="0",
                 year_end_deposit="0") -> dict:
    """Create independent one-year comparisons, never a synthetic track record."""
    starts = tuple(STARTING_BALANCES if starting_balances is None else starting_balances)
    goals = tuple(ANNUAL_INCOME_GOALS if annual_income_goals is None else annual_income_goals)
    rates = tuple(() if annual_returns_pct is None else annual_returns_pct)
    if not starts or not goals:
        raise ValueError("At least one starting balance and income goal are required")
    cost = _amount(fixed_annual_cost, "fixed_annual_cost")
    deposit = _amount(year_end_deposit, "year_end_deposit")
    requirements = [goal_requirement(start, goal, cost)
                    for start in starts for goal in goals]
    projections = [project_first_year(start, rate, goal, cost, deposit)
                   for start in starts for goal in goals for rate in rates]
    return {
        "report_kind": "illustrative_income_arithmetic",
        "strategy_performance_verified": False,
        "actual_withdrawal_eligibility_verified": False,
        "assumptions": {
            "horizon_years": 1,
            "currency": "USD",
            "return_basis": "after variable trading costs; before fixed annual cost and personal taxes",
            "fixed_annual_cost": _money(cost),
            "year_end_deposit": _money(deposit),
            "deposit_timing": "year-end, after the investment return; earns no return in this comparison",
            "withdrawal_timing": "year-end, capped at positive net profit and the income goal",
            "cash_and_reserves": "assumes gains can be realized; no tax or retained-profit reserve is modeled",
            "return_estimate": "none; projections use only explicitly supplied return scenarios",
        },
        "goal_requirements": requirements,
        "independent_one_year_scenarios": projections,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--starting-balances", nargs="+", default=STARTING_BALANCES)
    parser.add_argument("--income-goals", nargs="+", default=ANNUAL_INCOME_GOALS)
    parser.add_argument("--annual-returns-pct", nargs="+", default=None,
                        help="Explicit percentage scenarios, e.g. -20 0 5 10 20; not forecasts")
    parser.add_argument("--fixed-annual-cost", default="0")
    parser.add_argument("--year-end-deposit", default="0")
    args = parser.parse_args(argv)
    try:
        report = build_report(
            starting_balances=args.starting_balances,
            annual_income_goals=args.income_goals,
            annual_returns_pct=args.annual_returns_pct,
            fixed_annual_cost=args.fixed_annual_cost,
            year_end_deposit=args.year_end_deposit,
        )
    except (ValueError, InvalidOperation) as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
