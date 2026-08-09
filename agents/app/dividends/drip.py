"""Dividend DRIP -- payout scheduling, reinvestment, and total-return truth.

A dividend holding pays a distribution on a schedule. With DRIP on, that
payout buys more shares of the same holding and the position compounds.
With DRIP off it banks as cash (cumulative_dist).

WHY THE SCHEDULE MATTERS (fixed 2026-08-09)
This module used to pay EVERY holding every 7 days at 1/52 of its annual
yield. The annual dollar total came out right, but the timing was
invented. Two consequences, both bad:

  1. A quarterly payer received 52 compounding events a year instead of
     4. DRIP compounding was overstated for every holding that is not a
     genuinely weekly fund -- which is nearly all of them.
  2. No strategy that depends on WHEN a distribution lands could be
     tested at all -- ex-date ladders, capture, staggering cash so it
     arrives when there is something to buy. Every holding paid on the
     same 7-day clock, so there was nothing to schedule around.

Frequency now comes from the holding, and an ex-date from the calendar
overrides the interval when one is known.

THE YIELD TRAP (Mike's AIYY loss -- real money, 2026)
A fund can pay a large distribution straight out of its own NAV. Yield
rises mechanically as price falls, so ranking candidates by yield selects
hardest for the funds decaying fastest: the payout looks best exactly
where the capital is worst. The defence is NOT to ban high yields -- it
is to score on TOTAL RETURN (price change plus distributions received)
and to say the signature out loud when income is positive while total
return is negative. That is `yield_trap()`.

Modeled / paper, like the rest of Trezo.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

# Payouts per year by declared frequency.
FREQUENCIES = {
    "weekly": 52,
    "biweekly": 26,
    "semimonthly": 24,
    "monthly": 12,
    "quarterly": 4,
    "semiannual": 2,
    "annual": 1,
}

# Unknown frequency defaults to quarterly -- the most common schedule for
# dividend equities, and the CONSERVATIVE choice: assuming a slower payout
# understates compounding rather than overstating it. A model that guides
# real capital should err toward the smaller number.
DEFAULT_FREQUENCY = "quarterly"

# Retained so older callers still import cleanly. Do not use in new code:
# they encode the every-holding-is-weekly assumption this module fixed.
DISTRIBUTION_INTERVAL_DAYS = 7
PERIODS_PER_YEAR = 52


def payout_frequency(position: dict) -> str:
    """This holding's declared payout frequency, normalised."""
    raw = str(position.get("dist_frequency") or "").strip().lower()
    return raw if raw in FREQUENCIES else DEFAULT_FREQUENCY


def periods_per_year(frequency: str) -> int:
    return FREQUENCIES.get(str(frequency or "").lower(), FREQUENCIES[DEFAULT_FREQUENCY])


def interval_days(frequency: str) -> int:
    """Days between payouts. 365 / periods, floored at 1."""
    return max(1, round(365.0 / periods_per_year(frequency)))


def distribution_due(position: dict, today: Optional[date] = None,
                     ex_date: Optional[str] = None) -> bool:
    """Is a distribution due?

    A known ex-date wins: real calendars beat a modeled interval. Without
    one, fall back to this holding's own frequency interval -- not the
    old flat 7 days.
    """
    today = today or date.today()
    last = position.get("last_distribution_date")
    last_d = None
    if last:
        try:
            last_d = date.fromisoformat(str(last)[:10])
        except Exception:  # noqa: BLE001
            last_d = None

    if ex_date:
        try:
            ex = date.fromisoformat(str(ex_date)[:10])
        except Exception:  # noqa: BLE001
            ex = None
        if ex is not None:
            # Due once the ex-date has arrived and we have not already
            # paid on or after it.
            if today >= ex and (last_d is None or last_d < ex):
                return True
            return False

    if last_d is None:
        return True
    return (today - last_d).days >= interval_days(payout_frequency(position))


def period_distribution(position_value: float, yield_pct: float,
                        periods: Optional[int] = None) -> float:
    """One period's modeled distribution from an ANNUAL yield.

    `periods` is payouts per year. Passing None keeps the historical
    52-per-year behaviour so old callers do not silently change meaning;
    new callers should pass periods_per_year(payout_frequency(pos)).
    """
    v = max(0.0, float(position_value or 0))
    y = max(0.0, float(yield_pct or 0))
    n = int(periods or PERIODS_PER_YEAR)
    if n <= 0:
        n = PERIODS_PER_YEAR
    return round(v * (y / 100.0) / n, 2)


def ex_date_price(price: float, dist_per_share: float) -> float:
    """Price after the ex-date drop.

    A distribution comes out of the fund. On the ex-date the price falls
    by roughly the distribution, and a real DRIP buys AFTER that drop --
    so it gets slightly more shares than buying at the pre-drop price.
    Modeling the purchase at the undropped price quietly understates
    share count while overstating the position's value.
    """
    p = max(0.0, float(price or 0))
    d = max(0.0, float(dist_per_share or 0))
    return round(max(0.01, p - d), 6) if p > 0 else 0.0


def total_return(shares: float, price: float, avg_cost: float,
                 cumulative_dist: float) -> dict:
    """Price return, income return, and the total. The only honest score.

    Yield alone cannot tell you whether a holding made money; a fund
    paying 60% while its NAV halves is a loss wearing an income label.
    """
    sh = max(0.0, float(shares or 0))
    px = max(0.0, float(price or 0))
    cost_ps = max(0.0, float(avg_cost or 0))
    inc = max(0.0, float(cumulative_dist or 0))

    invested = sh * cost_ps
    if invested <= 0:
        return {"invested": 0.0, "market_value": round(sh * px, 2),
                "price_pnl": 0.0, "income": round(inc, 2),
                "total_pnl": round(inc, 2), "price_return_pct": 0.0,
                "income_return_pct": 0.0, "total_return_pct": 0.0}

    market_value = sh * px
    price_pnl = market_value - invested
    total_pnl = price_pnl + inc
    return {
        "invested": round(invested, 2),
        "market_value": round(market_value, 2),
        "price_pnl": round(price_pnl, 2),
        "income": round(inc, 2),
        "total_pnl": round(total_pnl, 2),
        "price_return_pct": round(price_pnl / invested * 100.0, 2),
        "income_return_pct": round(inc / invested * 100.0, 2),
        "total_return_pct": round(total_pnl / invested * 100.0, 2),
    }


def yield_trap(tr: dict) -> Optional[str]:
    """Name the AIYY signature: income positive, total return negative.

    Returns a plain-language warning, or None when the holding is fine.
    This does not ban anything -- a high yield is not the problem. Being
    paid your own capital back and calling it income is the problem.
    """
    if not tr or tr.get("invested", 0) <= 0:
        return None
    income = float(tr.get("income_return_pct") or 0)
    total = float(tr.get("total_return_pct") or 0)
    price = float(tr.get("price_return_pct") or 0)
    if income > 0 and total < 0:
        return (f"Distributions paid {income:.1f}% but the price fell "
                f"{abs(price):.1f}%, so the position is down "
                f"{abs(total):.1f}% overall. The payout is coming out of "
                f"the fund's own value -- this is return of capital "
                f"wearing an income label, not profit.")
    if income > 0 and price < 0 and total >= 0 and income > 0 and price < 0:
        eaten = abs(price) / income * 100.0 if income else 0.0
        if eaten >= 50.0:
            return (f"Price decay has eaten {eaten:.0f}% of the "
                    f"distributions. Still net positive, but the margin "
                    f"is thin and this is the shape that precedes a loss.")
    return None


def drip_explanation(ticker: str, dist: float, drip_on: bool,
                     shares_added: float, price: float,
                     frequency: str = DEFAULT_FREQUENCY) -> str:
    """A plain-language note on what happened with one distribution."""
    every = {52: "weekly", 26: "every two weeks", 24: "twice a month",
             12: "monthly", 4: "quarterly", 2: "twice a year",
             1: "yearly"}.get(periods_per_year(frequency), str(frequency))
    if drip_on and shares_added > 0:
        return (f"{ticker} paid a ${dist:,.2f} distribution ({every}). "
                f"With DRIP on, it bought {shares_added:.4f} more shares "
                f"at ${price:,.2f} - those new shares now earn "
                f"distributions of their own.")
    return (f"{ticker} paid a ${dist:,.2f} distribution ({every}), banked "
            f"as cash (DRIP is off for this holding).")
