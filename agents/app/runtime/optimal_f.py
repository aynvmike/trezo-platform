"""How much to bet -- optimal f, and the drawdown it buys.

Built 2026-08-05 from Ralph Vince, *The Mathematics of Money Management*
(Wiley, 1992), chapter 1. Phase 2 of Trezo's library plan. Formulas are
attributed and re-implemented; no text is reproduced.

THE PROBLEM THIS SOLVES
-----------------------
Trezo caps deployment with TREZO_MAX_DEPLOY_X = 1.25. That number was chosen
because it looked sensible. Nothing derives it, nothing tests it, and nobody
can say what fraction of the theoretical optimum it represents or what
drawdown it implies. This module makes those questions answerable.

WHY BET SIZE IS NOT A DETAIL
----------------------------
Returns compound MULTIPLICATIVELY. A sequence of trades does not add up, it
multiplies out, and multiplication has a property addition does not: one zero
destroys everything before it. Vince's HPR formulation makes this explicit --
at f = 1 the biggest historical loss produces a holding-period return of
exactly 0, and any wealth multiplied by zero is gone regardless of how well
the previous hundred trades went.

The consequence is that the SAME set of trades can compound to a fortune or to
nothing depending only on the fraction risked. Bet size is not a refinement
applied after strategy selection; it is a first-order determinant of the
outcome, and the only one fully under the trader's control.

THE ASYMMETRY THAT MATTERS
--------------------------
The growth curve rises to a peak at optimal f and then falls away. Being
BELOW the optimum costs you growth, slowly and recoverably. Being ABOVE it
costs you growth too -- and past a further point the geometric mean drops
under 1, at which point the strategy loses money on a compounding basis even
though its average trade is still positive. Chan's example of this: at a
leverage where the growth rate reaches -1, the account is wiped out.

So the errors are not symmetric, and the right response is to sit deliberately
BELOW the estimated optimum. This module reports that distance rather than
recommending a number.

A CAVEAT VINCE HIMSELF INSISTS ON
---------------------------------
Optimal f is acutely sensitive to the single biggest historical loss, and he
argues against shrinking that loss to make the answer more comfortable -- a
worse loss than any yet seen is always possible, and an algorithm that
predicts the maximum loss fails on the one occasion that matters. Treat any f
computed here as an UPPER BOUND derived from a sample that has not yet seen
its worst day.

NOTHING HERE SIZES A TRADE. These are measurements for proposals.
"""

from __future__ import annotations

import math
from typing import Optional, Sequence


def hpr(trade: float, f: float, biggest_loss: float) -> float:
    """Holding Period Return for one trade at fraction f.

    Vince (1.11): HPR = 1 + f * (-Trade / Biggest Loss), with Biggest Loss
    negative. Equivalently 1 + f * trade / |biggest_loss|, which is the form
    used here because it is harder to get the signs wrong.

    At f = 1 the biggest loss returns exactly 0 -- total ruin.
    """
    bl = abs(float(biggest_loss))
    if bl <= 0:
        return 1.0
    return 1.0 + float(f) * (float(trade) / bl)


def twr(trades: Sequence[float], f: float,
        biggest_loss: Optional[float] = None) -> Optional[float]:
    """Terminal Wealth Relative: final stake per unit of starting stake.

    Returns None if any HPR goes non-positive -- that is ruin, and a number
    would imply the account survived to keep compounding.
    """
    if not trades:
        return None
    bl = biggest_loss if biggest_loss is not None else min(trades)
    if bl >= 0:
        return None
    out = 1.0
    for t in trades:
        h = hpr(t, f, bl)
        if h <= 0:
            return None
        out *= h
    return out


def geometric_mean(trades: Sequence[float], f: float,
                   biggest_loss: Optional[float] = None) -> Optional[float]:
    """Growth factor per trade. Below 1.0 the system loses money when
    returns are reinvested, even if its average trade is positive."""
    w = twr(trades, f, biggest_loss)
    if w is None or w <= 0:
        return None
    return w ** (1.0 / len(trades))


def optimal_f(trades: Sequence[float], step: float = 0.001
              ) -> Optional[dict]:
    """The fraction that maximises geometric growth.

    Vince searches f from 0.01 to 1.0; this uses a finer step because the
    peak is flat near the top and a coarse grid overstates precision.
    """
    if not trades or len(trades) < 3:
        return None
    bl = min(trades)
    if bl >= 0:
        return None                      # no losing trade: f is unbounded
    best_f, best_g = 0.0, None
    f = step
    while f <= 1.0:
        g = geometric_mean(trades, f, bl)
        if g is not None and (best_g is None or g > best_g):
            best_f, best_g = f, g
        f += step
    if best_g is None:
        return None
    return {
        "optimal_f": round(best_f, 4),
        "geometric_mean": round(best_g, 6),
        "growth_per_trade_pct": round((best_g - 1) * 100, 4),
        "biggest_loss": round(bl, 2),
        "f_dollar": round(abs(bl) / best_f, 2) if best_f > 0 else None,
        "geometric_average_trade": (
            round((best_g - 1) * (abs(bl) / best_f), 2) if best_f > 0 else None),
        "n_trades": len(trades),
    }


def growth_curve(trades: Sequence[float],
                 fractions: Sequence[float]) -> list[dict]:
    """Geometric mean at each fraction -- the shape of the hill."""
    bl = min(trades) if trades else 0.0
    rows = []
    for f in fractions:
        g = geometric_mean(trades, f, bl) if bl < 0 else None
        rows.append({
            "f": round(f, 4),
            "geometric_mean": round(g, 6) if g else None,
            "compounding": (None if g is None
                            else "grows" if g > 1 else "shrinks"),
        })
    return rows


def simulate_drawdown(trades: Sequence[float], f: float,
                      biggest_loss: Optional[float] = None,
                      starting_stake: float = 1.0) -> Optional[dict]:
    """Walk the equity path at fraction f and report the worst peak-to-trough.

    This is the number that actually decides whether a fraction is livable.
    Growth is theoretical; drawdown is what a person has to sit through, and
    Vince's own point is that optimal f produces drawdowns most traders will
    not tolerate -- which is an argument for choosing a fraction by the
    drawdown you can bear rather than by the growth you would like.
    """
    if not trades:
        return None
    bl = biggest_loss if biggest_loss is not None else min(trades)
    if bl >= 0:
        return None
    equity = float(starting_stake)
    peak = equity
    worst = 0.0
    for t in trades:
        h = hpr(t, f, bl)
        if h <= 0:
            return {"f": f, "ruined": True, "max_drawdown_pct": 100.0,
                    "final_multiple": 0.0}
        equity *= h
        peak = max(peak, equity)
        dd = (equity - peak) / peak
        worst = min(worst, dd)
    return {
        "f": round(f, 4),
        "ruined": False,
        "max_drawdown_pct": round(abs(worst) * 100, 2),
        "final_multiple": round(equity / starting_stake, 4),
    }


def fraction_for_drawdown(trades: Sequence[float], max_dd_pct: float,
                          step: float = 0.001) -> Optional[dict]:
    """The largest fraction whose historical path stays inside a drawdown
    the user is willing to sit through.

    This inverts the usual question. Instead of "what is optimal", it asks
    "what can I actually live with", which is the question that decides
    whether a plan survives contact with a bad month.
    """
    if not trades or len(trades) < 3:
        return None
    bl = min(trades)
    if bl >= 0:
        return None
    best = None
    f = step
    while f <= 1.0:
        sim = simulate_drawdown(trades, f, bl)
        if sim and not sim["ruined"] and sim["max_drawdown_pct"] <= max_dd_pct:
            best = {"f": round(f, 4), **{k: v for k, v in sim.items() if k != "f"}}
        f += step
    return best
