"""Is this option premium rich or cheap? -- the volatility edge.

Built 2026-08-05 from Sheldon Natenberg, *Option Volatility & Pricing*
(McGraw-Hill), phase 3 of Trezo's library plan. Principles are attributed; no
text is reproduced.

A NOTE ON THE SOURCE. The copy in the drop-box is a CONDENSED edition -- chapter
summaries rather than the full text -- so unlike de Prado and Vince there are no
published worked examples to verify an implementation against. The statistics
here are therefore verified directly (percentile behaviour, edge cases) rather
than reproduced from the book, and that difference is stated rather than hidden.

THE PRINCIPLE
-------------
Natenberg's central claim is that option trading is VOLATILITY trading. An
option's price is mostly a bet on how much the underlying will move. The seller
earns when the volatility priced INTO the option (implied) turns out to exceed
what the underlying actually DOES (realized). That gap is the edge, and it is
the only durable one in premium selling.

Two supporting facts he leans on: volatility exhibits serial correlation and
MEAN REVERSION -- markets return toward an average volatility over time, which
is what makes "high relative to its own history" a meaningful and tradeable
statement. And implied volatility is a forecast, frequently a poor one, so the
difference between the forecast and the outcome is where the money sits.

THE GAP THIS EXPOSES IN TREZO
-----------------------------
Trezo's wheel computes its option premium with theoretical_price() using an
`iv` that comes from iv_from_candles() -- which is REALIZED volatility measured
from the underlying's own candles. Implied is therefore set EQUAL to realized
by construction.

The consequence is not subtle: the variance premium is identically zero in
Trezo's model, so the wheel cannot distinguish an expensive option from a cheap
one, and its expected edge from volatility is exactly nil. Whatever the wheel
earns comes from direction and assignment, not from selling volatility -- which
is the thing it is nominally in the business of doing.

Alpaca DOES serve real option quotes, and brokers/alpaca_data.get_option_quote
is already used by the scanner and the position monitor. The wheel's ENTRY
decision simply never asks.

NOTHING HERE PLACES A TRADE. Measurement for proposals.
"""

from __future__ import annotations

import math
from typing import Optional, Sequence


# --------------------------------------------------------------------------
# Realized volatility history -- the yardstick a current reading is ranked in
# --------------------------------------------------------------------------

def realized_vol_series(candles: Sequence, window: int = 20,
                        estimator: str = "") -> list[float]:
    """Rolling annualised realized volatility over a trailing window.

    Uses the range-based estimator shipped earlier today, so the history is
    measured with the same instrument as the present -- comparing a
    Yang-Zhang reading against a close-to-close history would rank a number
    against a differently-calibrated yardstick and quietly mislead.
    """
    try:
        from app.options.pricing import estimate_vol_from_candles
    except Exception:  # noqa: BLE001
        return []
    out: list[float] = []
    n = len(candles)
    if n < window + 2:
        return out
    for i in range(window, n + 1):
        r = estimate_vol_from_candles(candles[i - window:i], estimator)
        v = float(r.get("vol") or 0)
        if v > 0:
            out.append(v)
    return out


def vol_percentile(current: float, history: Sequence[float]) -> Optional[float]:
    """Where `current` sits inside its own history, 0-100.

    This is the realized-volatility analogue of IV rank. 80 means the reading
    is higher than 80% of the trailing period -- the regime in which selling
    premium has historically been worth doing.
    """
    hist = [h for h in history if h and h > 0]
    if len(hist) < 10 or current is None or current <= 0:
        return None
    below = len([h for h in hist if h < current])
    return round(100.0 * below / len(hist), 1)


def vol_rank(current: float, history: Sequence[float]) -> Optional[float]:
    """The other common convention: position between the period's low and
    high rather than a percentile. Reported alongside because the two
    disagree on skewed distributions and traders quote both."""
    hist = [h for h in history if h and h > 0]
    if len(hist) < 10 or current is None or current <= 0:
        return None
    lo, hi = min(hist), max(hist)
    if hi <= lo:
        return None
    return round(100.0 * (current - lo) / (hi - lo), 1)


# --------------------------------------------------------------------------
# The variance premium -- what the seller is actually paid for
# --------------------------------------------------------------------------

def implied_vol_from_price(option_type: str, price: float, spot: float,
                           strike: float, days: int,
                           lo: float = 0.01, hi: float = 5.0,
                           tol: float = 1e-5) -> Optional[float]:
    """Back out implied volatility from a REAL market premium, by bisection.

    Black-Scholes price is monotonic in volatility, so bisection is both
    sufficient and robust -- no derivative, no failure to converge.
    """
    try:
        from app.options.pricing import theoretical_price
    except Exception:  # noqa: BLE001
        return None
    if price <= 0 or spot <= 0 or strike <= 0 or days <= 0:
        return None
    def px(v: float) -> Optional[float]:
        try:
            return float(theoretical_price(option_type, spot, strike, days, v).premium)
        except Exception:  # noqa: BLE001
            return None
    p_lo, p_hi = px(lo), px(hi)
    if p_lo is None or p_hi is None:
        return None
    if price < p_lo or price > p_hi:
        return None                      # outside what any vol can produce
    for _ in range(100):
        mid = (lo + hi) / 2.0
        p = px(mid)
        if p is None:
            return None
        if abs(p - price) < tol:
            return round(mid, 6)
        if p < price:
            lo = mid
        else:
            hi = mid
    return round((lo + hi) / 2.0, 6)


def variance_premium(implied: float, realized: float) -> Optional[dict]:
    """What the option is charging above what the stock has been doing.

    Positive means the seller is being paid MORE than recent history says the
    move is worth -- the condition premium selling needs. Negative means the
    option is cheap relative to the underlying's behaviour, and selling it is
    taking the wrong side of the trade.
    """
    try:
        iv, rv = float(implied), float(realized)
    except (TypeError, ValueError):
        return None
    if iv <= 0 or rv <= 0:
        return None
    return {
        "implied_vol_pct": round(iv * 100, 2),
        "realized_vol_pct": round(rv * 100, 2),
        "premium_points": round((iv - rv) * 100, 2),
        "premium_ratio": round(iv / rv, 3),
        "seller_favoured": bool(iv > rv),
    }


# --------------------------------------------------------------------------
# The verdict a wheel lane would act on
# --------------------------------------------------------------------------

RICH_RATIO = 1.20      # implied at least 20% above realized
CHEAP_RATIO = 1.00     # at or below realized: selling is the wrong side
HIGH_RANK = 60.0       # realized vol in the upper part of its own history


def premium_verdict(implied: Optional[float], realized: Optional[float],
                    vol_pct_rank: Optional[float] = None) -> dict:
    """Plain-language judgement for a premium-selling decision.

    Deliberately conservative about the unknown case: when implied cannot be
    obtained the verdict is UNKNOWN, never a default to "fine". A wheel that
    treats a missing quote as permission is the same class of bug as a broker
    check that reads a failed call as all-clear.
    """
    vp = variance_premium(implied, realized) if (implied and realized) else None
    if vp is None:
        return {
            "verdict": "UNKNOWN",
            "why": ("no real option quote available, so it cannot be said "
                    "whether this premium is rich or cheap"),
            "sell_premium_ok": False,
        }
    ratio = vp["premium_ratio"]
    if ratio >= RICH_RATIO:
        v, why = "RICH", (
            f"implied {vp['implied_vol_pct']}% is {(ratio - 1) * 100:.0f}% above "
            f"realized {vp['realized_vol_pct']}% -- the seller is being paid "
            f"more than recent behaviour justifies")
        ok = True
    elif ratio > CHEAP_RATIO:
        v, why = "FAIR", (
            f"implied {vp['implied_vol_pct']}% is only modestly above realized "
            f"{vp['realized_vol_pct']}% -- a thin edge that costs and slippage "
            f"can erase")
        ok = True
    else:
        v, why = "CHEAP", (
            f"implied {vp['implied_vol_pct']}% is at or BELOW realized "
            f"{vp['realized_vol_pct']}% -- selling here is taking the wrong "
            f"side of the volatility trade")
        ok = False
    if vol_pct_rank is not None:
        why += (f"; realized vol sits at the {vol_pct_rank:.0f}th percentile "
                f"of its own trailing history")
        if vol_pct_rank < 20 and v == "RICH":
            why += (" -- but a quiet regime means the option may simply be "
                    "priced for a coming event")
    return {"verdict": v, "why": why, "sell_premium_ok": ok, **vp,
            "vol_percentile": vol_pct_rank}
