"""R-multiples and expectancy -- one unit for every trade in the book.

Built 2026-08-05 from Van K. Tharp, *Trade Your Way to Financial Freedom*
(McGraw-Hill), phase 5 of the library plan. Formulas are attributed and
re-implemented; no text is reproduced. This supersedes the earlier
THARP_POSITION_SIZING_AND_EXPECTANCY.md note, which was written from
principle before the book was available.

THE IDEA
--------
An R-multiple is a trade's result divided by the risk taken to get it. Risk
$50 and make $150, that is a +3R trade. Risk $50 and hit the stop, that is
-1R. The dollar amounts stop mattering; what matters is the multiple.

This is quietly powerful because it makes every trade in the book
COMPARABLE. A $12 crypto scalp and a $400 options position are unreadable
side by side in dollars, and identical in R if both made three times what
they risked. Trezo has been reporting dollars and profit factors, which
conceal exactly this.

EXPECTANCY is then simply the MEAN of the R-multiple distribution: what the
system makes per dollar risked, averaged over many trades. Tharp's worked
example -- a bag of 60 marbles that win 1R and 40 that lose 1R -- gives a net
of +20R over 100 draws, so expectancy is 0.2R.

OPPORTUNITY is the other half, and the half most people skip. Expectancy says
what one trade is worth; opportunity says how often you get to take one. His
comparison: a game with 0.2R expectancy played 60 times an hour returns 12R,
while a better-looking 0.78R game played only 12 times returns 9.36R. The
worse system wins because it plays more often.

  That is Mike's velocity mandate of 2026-07-24 -- "prioritise the trades that
  can be settled in a day, the 24 HR market" -- stated independently by Tharp,
  and it agrees with de Prado's finding that Sharpe scales with the square root
  of the number of bets. Three sources, one conclusion.

A LOSS BIGGER THAN 1R IS A DIFFERENT KIND OF EVENT
--------------------------------------------------
Tharp reframes the old rule about not losing money as something actionable:
keep losses to 1R or less. A -1R loss is the system working. A -3R loss means
the exit failed -- a gap, a slipped stop, a rule that did not fire. Those
should be counted separately, because they are not strategy outcomes at all.

NOTHING HERE SIZES OR BLOCKS A TRADE. Measurement for the digest and proposals.
"""

from __future__ import annotations

import math
from typing import Optional, Sequence


def r_multiple(pnl: float, initial_risk: float) -> Optional[float]:
    """A trade's result in units of the risk taken.

    `initial_risk` is the dollar amount at stake when the trade opened --
    quantity times the distance from entry to stop. Not the position size,
    and not the margin: the amount that would actually have been lost.
    """
    try:
        risk = abs(float(initial_risk))
        if risk <= 0:
            return None
        return float(pnl) / risk
    except (TypeError, ValueError):
        return None


def risk_from_geometry(entry: float, stop: float, quantity: float
                       ) -> Optional[float]:
    """Initial risk in dollars, from the numbers Trezo already stores."""
    try:
        e, s, q = float(entry), float(stop), float(quantity)
    except (TypeError, ValueError):
        return None
    if e <= 0 or s <= 0 or q <= 0:
        return None
    return abs(e - s) * q


def expectancy(r_multiples: Sequence[float]) -> Optional[dict]:
    """The mean R-multiple, plus the shape of the distribution around it.

    The mean alone is not enough to act on: two systems with the same
    expectancy and very different spreads demand very different bet sizes,
    which is the bridge to runtime/optimal_f.py.
    """
    rs = [float(r) for r in r_multiples if r is not None]
    n = len(rs)
    if n < 2:
        return None
    mean = sum(rs) / n
    var = sum((r - mean) ** 2 for r in rs) / (n - 1)
    sd = math.sqrt(var) if var > 0 else 0.0
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    # Losses worse than -1R are exit FAILURES, not strategy outcomes.
    blown = [r for r in losses if r < -1.0001]
    return {
        "trades": n,
        "expectancy_r": round(mean, 4),
        "stdev_r": round(sd, 4),
        "win_rate_pct": round(100.0 * len(wins) / n, 1),
        "avg_win_r": round(sum(wins) / len(wins), 3) if wins else 0.0,
        "avg_loss_r": round(sum(losses) / len(losses), 3) if losses else 0.0,
        "best_r": round(max(rs), 2),
        "worst_r": round(min(rs), 2),
        "losses_worse_than_1R": len(blown),
        "worst_case_note": (
            f"{len(blown)} of {len(losses)} losses exceeded 1R -- these are exit "
            f"failures (gaps, slipped stops, rules that did not fire), not "
            f"strategy outcomes, and should be investigated separately"
            if blown else
            "every loss was 1R or smaller -- the exits did their job"),
        "positive": mean > 0,
    }


def expectunity(expectancy_r: float, opportunities: float) -> float:
    """Expectancy multiplied by how often you get to use it.

    Tharp's point in one function: a smaller edge taken often beats a larger
    edge taken rarely. This is what makes a 24/7 market structurally
    valuable, independent of any skill in it.
    """
    return float(expectancy_r) * float(opportunities)


def compare_systems(a_name: str, a_exp: float, a_opps: float,
                    b_name: str, b_exp: float, b_opps: float) -> dict:
    """Which system is actually worth more per period?"""
    a, b = expectunity(a_exp, a_opps), expectunity(b_exp, b_opps)
    better = a_name if a > b else b_name if b > a else "tie"
    return {
        a_name: {"expectancy_r": a_exp, "opportunities": a_opps,
                 "r_per_period": round(a, 3)},
        b_name: {"expectancy_r": b_exp, "opportunities": b_opps,
                 "r_per_period": round(b, 3)},
        "better": better,
        "why": (f"{better} returns more R per period even though "
                f"{'it has the smaller edge per trade' if (better == a_name and a_exp < b_exp) or (better == b_name and b_exp < a_exp) else 'the per-trade edges differ'}"),
    }
