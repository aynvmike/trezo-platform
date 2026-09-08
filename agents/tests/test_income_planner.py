"""Income goals must not manufacture profits or disguise new deposits.

Exercises the offline planner and its real CLI without credentials,
fixtures, ledger writes or network; compatible with both required gates.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import load_module, run_tests  # noqa: E402

planner = load_module("app.paper.income_planner")


def test_defaults_have_both_starting_cases_and_no_assumed_profit():
    report = planner.build_report()
    assert report["strategy_performance_verified"] is False
    assert report["actual_withdrawal_eligibility_verified"] is False
    assert report["independent_one_year_scenarios"] == []
    rows = report["goal_requirements"]
    assert {(r["starting_balance"], r["annual_income_goal"]) for r in rows} == {
        ("1000.00", "20000.00"), ("1000.00", "40000.00"),
        ("5000.00", "20000.00"), ("5000.00", "40000.00"),
    }


def test_required_return_uses_invested_capital_and_includes_fixed_costs():
    small = planner.goal_requirement("1000", "20000")
    larger = planner.goal_requirement("5000", "40000", "100")
    assert small["required_trading_return_pct"] == "2000.0000"
    assert larger["required_trading_return_pct"] == "802.0000"


def test_a_deposit_does_not_become_profit_or_fund_an_income_payout():
    row = planner.project_first_year("1000", "0", "20000", year_end_deposit="20000")
    assert row["equity_before_withdrawal"] == "21000.00"
    assert row["net_profit_before_personal_taxes"] == "0.00"
    assert row["illustrative_profit_only_withdrawal"] == "0.00"
    assert row["income_goal_met"] is False


def test_costs_reduce_payout_and_do_not_disappear_behind_the_goal():
    row = planner.project_first_year("1000", "20", "20000", "100")
    assert row["net_profit_before_personal_taxes"] == "100.00"
    assert row["illustrative_profit_only_withdrawal"] == "100.00"
    assert row["remaining_net_equity"] == "1000.00"
    assert row["unmet_income_goal"] == "19900.00"


def test_losses_with_a_deposit_still_show_a_loss_and_zero_payout():
    row = planner.project_first_year("1000", "-20", "20000", "50", "200")
    assert row["net_profit_before_personal_taxes"] == "-250.00"
    assert row["remaining_net_equity"] == "950.00"
    assert row["illustrative_profit_only_withdrawal"] == "0.00"


def test_a_smaller_income_request_leaves_the_rest_of_the_profit_invested():
    row = planner.project_first_year("5000", "10", "300")
    assert row["illustrative_profit_only_withdrawal"] == "300.00"
    assert row["remaining_net_equity"] == "5200.00"
    assert row["income_goal_met"] is True


def test_accumulation_keeps_gains_and_deposits_separately_identified():
    row = planner.project_first_year("5000", "20", year_end_deposit="1000")
    assert row["net_profit_before_personal_taxes"] == "1000.00"
    assert row["year_end_deposit"] == "1000.00"
    assert row["remaining_net_equity"] == "7000.00"
    assert row["income_goal_met"] is None


def test_exhausted_capital_does_not_hide_unpaid_costs_or_create_a_top_up():
    row = planner.project_first_year("1000", "-100", "100", "50")
    assert row["remaining_net_equity"] == "-50.00"
    assert row["additional_cash_required_for_unfunded_costs"] == "50.00"
    assert row["year_end_deposit"] == "0.00"
    assert row["illustrative_profit_only_withdrawal"] == "0.00"


def test_invalid_money_and_nonfinite_or_unsupported_returns_are_rejected():
    invalid_cases = [
        ("0", "10", "100"), ("-1", "10", "100"),
        (True, "10", "100"), ("1000.001", "10", "100"),
        ("1000", "nan", "100"), ("1000", "Infinity", "100"),
        ("1000", True, "100"), ("1000", "bad", "100"),
        ("1000", "-101", "100"), ("1000", "10", "-1"),
        ("1000", "10", "100", "-1"),
        ("1000", "10", "100", "0", "-1"),
    ]
    for args in invalid_cases:
        try:
            planner.project_first_year(*args)
        except ValueError:
            continue
        raise AssertionError(f"invalid planning inputs accepted: {args}")


def test_each_explicit_return_is_an_independent_case_and_money_is_in_cents():
    report = planner.build_report(starting_balances=["1000.01"],
                                  annual_income_goals=["0"],
                                  annual_returns_pct=["0.5", "-20"])
    rows = report["independent_one_year_scenarios"]
    assert rows[0]["trading_result_before_fixed_cost"] == "5.00"
    assert rows[1]["starting_balance"] == "1000.01"
    assert rows[1]["remaining_net_equity"] == "800.01"


def test_cli_calls_the_planner_and_labels_output_as_illustrative():
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = planner.main(["--annual-returns-pct", "20",
                             "--income-goals", "20000",
                             "--year-end-deposit", "500"])
    assert code == 0
    report = json.loads(out.getvalue())
    assert report["report_kind"] == "illustrative_income_arithmetic"
    rows = report["independent_one_year_scenarios"]
    assert [r["remaining_net_equity"] for r in rows] == ["1500.00", "5500.00"]
    assert [r["illustrative_profit_only_withdrawal"] for r in rows] == ["200.00", "1000.00"]


def test_cli_refuses_invalid_input_without_printing_a_projection():
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            planner.main(["--starting-balances", "0"])
        except SystemExit as exc:
            assert exc.code == 2
        else:
            raise AssertionError("invalid CLI input did not fail")
    assert out.getvalue() == ""
    assert "starting_balance must be positive" in err.getvalue()


if __name__ == "__main__":
    sys.exit(run_tests(dict(globals())))
