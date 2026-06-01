"""Dividend DRIP - the reinvestment + compounding engine.

A dividend holding (a YieldMax fund, a dividend stock) pays a
distribution on a schedule. With DRIP on, that payout buys more shares
of the same holding - the compounding KINDRIP gives a child's account,
here for the user's own Dividends layer. With DRIP off, the payout is
banked as cash (tracked in cumulative_dist).

Modeled / paper, like the rest of Trezo. Distributions are estimated
from each holding's dist_yield_pct (an annual distribution yield).
"""

from __future__ import annotations

from datetime import date
from typing import Optional

DISTRIBUTION_INTERVAL_DAYS = 7      # YieldMax-style weekly distributions
PERIODS_PER_YEAR = 52


def distribution_due(position: dict, today: Optional[date] = None) -> bool:
    """Is a distribution due for this holding? Weekly cadence."""
    today = today or date.today()
    last = position.get("last_distribution_date")
    if not last:
        return True
    try:
        last_d = date.fromisoformat(str(last)[:10])
    except Exception:  # noqa: BLE001
        return True
    return (today - last_d).days >= DISTRIBUTION_INTERVAL_DAYS


def period_distribution(position_value: float, yield_pct: float) -> float:
    """One period's modeled distribution, from an annual yield."""
    v = max(0.0, float(position_value or 0))
    y = max(0.0, float(yield_pct or 0))
    return round(v * (y / 100.0) / PERIODS_PER_YEAR, 2)


def drip_explanation(ticker: str, dist: float, drip_on: bool,
                     shares_added: float, price: float) -> str:
    """A plain-language note on what happened with one distribution."""
    if drip_on and shares_added > 0:
        return (f"{ticker} paid a ${dist:,.2f} distribution. With DRIP on, "
                f"it bought {shares_added:.4f} more shares at ${price:,.2f} - "
                f"those new shares now earn distributions of their own.")
    return (f"{ticker} paid a ${dist:,.2f} distribution, banked as cash "
            f"(DRIP is off for this holding).")
