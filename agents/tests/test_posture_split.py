"""The posture split after Mike's 2026-09-02 decision: widen the stock pool
for ALL books.

Pins the arithmetic (every posture still sums to 1.0), the new stocks
floors, the dollar budget the executor will see on an unpinned mid-size
book, and -- deliberately -- the trap that made the first attempt inert: a
per-book allocation_overrides dollar pin REPLACES the split, so the split
only governs a book whose stocks pin is blank.

run_all contract: plain zero-arg test_ functions, no fixtures, no .env, no
network. app.paper.allocation loads bare through _bootstrap; nothing here
reaches app.agents.activity_log.
"""
from tests import _bootstrap

_bootstrap.stub_config()
alloc = _bootstrap.load_module("app.paper.allocation")

NEW_STOCK_FLOORS = {"growth": 0.50, "balanced": 0.45, "income": 0.28, "velocity": 0.30}


def test_every_posture_sums_to_one_with_every_lane_funded():
    for posture, split in alloc.POSTURE_SPLIT.items():
        assert set(split) == set(alloc.MARKET_TYPES), (posture, split)
        assert all(v > 0 for v in split.values()), (posture, split)
        assert abs(sum(split.values()) - 1.0) < 1e-9, (posture, sum(split.values()))


def test_stocks_floors_mike_2026_09_02():
    for posture, floor in NEW_STOCK_FLOORS.items():
        assert alloc.POSTURE_SPLIT[posture]["stocks"] >= floor, (posture, alloc.POSTURE_SPLIT[posture])
    assert set(NEW_STOCK_FLOORS) == set(alloc.POSTURES)


def test_balanced_81k_book_gets_36_450_of_stock_room():
    plan = alloc.build_allocation(81_000, "balanced")
    assert plan.posture == "balanced" and plan.source == "user"
    assert plan.budgets["stocks"] == 36_450.0, plan.budgets


def test_budgets_sum_to_equity_without_overrides():
    for posture in alloc.POSTURES:
        plan = alloc.build_allocation(81_000, posture)
        assert abs(sum(plan.budgets.values()) - 81_000) < 0.05, (posture, plan.budgets)


def test_auto_posture_by_account_size():
    assert alloc.default_posture(5_030) == "growth"
    assert alloc.default_posture(77_641) == "balanced"
    assert alloc.default_posture(100_000) == "income"
    assert alloc.build_allocation(77_641.6).source == "auto"


def test_a_stocks_dollar_pin_still_replaces_the_split():
    """The exact trap of 2026-09-02: all three live books carried a stocks
    pin, so widening the split changed nothing until the pins were lifted.
    The pin semantics are Mike's explicit per-book setting and must stay."""
    plan = alloc.build_allocation(77_641.6, "auto", overrides={"stocks": 26_000})
    assert plan.budgets["stocks"] == 26_000.0
    unpinned = alloc.build_allocation(77_641.6, "auto")
    for lane in ("crypto", "options", "income", "forex"):
        assert plan.budgets[lane] == unpinned.budgets[lane], lane
    assert unpinned.budgets["stocks"] == round(77_641.6 * 0.45, 2)


if __name__ == "__main__":
    import sys
    sys.exit(_bootstrap.run_tests(dict(vars())))
