"""An exhausted budget cannot turn into an unconstrained position.

The executor supplies the minimum of broker buying power, pocket funds,
and lane cap. Zero must survive that final sizing boundary.
"""

from __future__ import annotations

import contextlib
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import load_module, run_tests, stub_config  # noqa: E402

stub_config()
sizing = load_module("app.paper.sizing")
settings = load_module("app.runtime.settings")


@contextlib.contextmanager
def _book_settings():
    old = settings.get_bot_settings
    settings.get_bot_settings = lambda uid=None: types.SimpleNamespace(
        max_position_pct=0.25, min_reward_risk=1.5)
    try:
        yield
    finally:
        settings.get_bot_settings = old


def _plan(budget, asset_type="stock"):
    with _book_settings():
        return sizing.plan_position(
            equity=10_000, entry_price=100, stop_price=95,
            target_price=110, risk_pct=0.01, asset_type=asset_type,
            buying_power=budget, user_id="test-book")


def test_zero_stock_buying_power_refuses_instead_of_sizing_from_equity():
    plan = _plan(0)
    assert plan.ok is False
    assert plan.quantity == 0 and plan.notional_usd == 0
    assert "Buying power" in plan.reject_reason


def test_zero_crypto_budget_cannot_be_ignored():
    plan = _plan(0, "crypto")
    assert plan.ok is False
    assert plan.quantity == 0


def test_negative_budgets_refuse_for_both_markets():
    for asset in ("stock", "crypto"):
        assert _plan(-1, asset).ok is False


def test_unknown_or_nonfinite_supplied_budgets_refuse():
    for budget in (float("nan"), float("inf"), float("-inf"), "unavailable"):
        for asset in ("stock", "crypto"):
            plan = _plan(budget, asset)
            assert plan.ok is False and plan.quantity == 0


def test_valid_budget_caps_actual_notional():
    stock = _plan(150)
    crypto = _plan(150, "crypto")
    assert stock.ok and stock.quantity == 1 and stock.notional_usd == 100
    assert crypto.ok and crypto.quantity == 1.5 and crypto.notional_usd == 150
    assert stock.capped and crypto.capped


def test_none_preserves_the_explicit_no_budget_contract():
    plan = _plan(None)
    assert plan.ok and plan.quantity == 20 and plan.risk_usd == 100


def test_exhausted_book_does_not_change_a_funded_books_plan():
    assert _plan(0).ok is False
    funded = _plan(1_000)
    assert funded.ok and funded.quantity == 10 and funded.notional_usd == 1_000


if __name__ == "__main__":
    sys.exit(run_tests(dict(globals())))
