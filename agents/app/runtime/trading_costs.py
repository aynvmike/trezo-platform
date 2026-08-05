"""What a trade really costs -- spread, fees, and who you are trading against.

Built 2026-08-05 from Larry Harris, *Trading and Exchanges: Market
Microstructure for Practitioners* (Oxford, 2002), chapter 14. Phase 4 of the
library plan. Principles are attributed; no text is reproduced.

SOURCE CAVEAT: the drop-box copy is a 113-page DRAFT EXCERPT of a roughly
640-page book. The framework below is drawn from the spread-components chapter,
which is present; much of the book is not. The Trezo findings this module acts
on came from reading Trezo's own code, so they do not depend on the excerpt
being complete.

THE IDEA THAT MATTERS
---------------------
Harris decomposes the bid/ask spread into two parts, and the second is the one
traders forget:

  * The TRANSACTION COST component pays the dealer for the ordinary costs of
    doing business -- systems, capital, inventory risk.
  * The ADVERSE SELECTION component pays the dealer for what they lose to
    better-informed traders. In his framing it is how dealers earn from the
    uninformed what they lose to the informed.

The consequence is uncomfortable and worth stating plainly: part of every
spread you cross is the market charging you on the assumption that somebody in
the flow knows more than you do. A cost model that treats the spread as a
service fee has missed half of what it is.

WHY THIS MATTERS TO TREZO SPECIFICALLY
--------------------------------------
The crypto scalp lane exits the moment an open gain covers modelled round-trip
cost -- 0.62%, from a 26bps fee and 5bps of slippage per side. So that single
modelled number sets the exit for an entire lane.

But the model was never measured:

  * SLIPPAGE_BPS = 5 is a FLAT constant applied to every asset. Harris's whole
    point is that this varies by instrument, by size relative to available
    liquidity, and by whether you cross the spread or post inside it. Trezo
    charges the same 5bps to BTC and to a thin alt.
  * Trezo had quote functions for stocks and for options but NONE for crypto,
    so the crypto spread was never even observed. (Added the same day as this
    module: brokers.alpaca_data.get_crypto_quote.)
  * CRYPTO_COMMISSION_BPS = 26 is labelled "Kraken taker" -- but broker-only
    mode routes crypto to ALPACA, whose crypto fees are tiered by 30-day
    volume. The number may be close; it has never been checked against the
    schedule that actually applies.

For a lane whose entire realised edge was 0.63%, an unmeasured cost is not a
detail. It is the difference between a thin edge and no edge.

NOTHING HERE BLOCKS A TRADE. Measurement for proposals.
"""

from __future__ import annotations

from typing import Optional


def half_spread_pct(bid: float, ask: float) -> Optional[float]:
    """Cost of crossing the spread ONE way, as a fraction of the mid.

    A market order pays roughly half the spread against the mid on entry and
    again on exit, so this is the honest per-side figure.
    """
    try:
        b, a = float(bid), float(ask)
    except (TypeError, ValueError):
        return None
    if b <= 0 or a <= 0 or a < b:
        return None
    mid = (a + b) / 2.0
    if mid <= 0:
        return None
    return ((a - b) / 2.0) / mid


def round_trip_cost(fee_bps: float, half_spread: Optional[float] = None,
                    extra_slippage_bps: float = 0.0) -> dict:
    """Everything a complete in-and-out trade costs, as a fraction.

    Kept separate rather than collapsed into one number so a proposal can see
    WHICH component dominates -- the fix for a fee problem and the fix for a
    spread problem are different.
    """
    fee = 2.0 * (float(fee_bps) / 10_000.0)
    spread = 2.0 * float(half_spread) if half_spread else 0.0
    slip = 2.0 * (float(extra_slippage_bps) / 10_000.0)
    total = fee + spread + slip
    return {
        "fee_pct": round(fee * 100, 4),
        "spread_pct": round(spread * 100, 4),
        "slippage_pct": round(slip * 100, 4),
        "total_pct": round(total * 100, 4),
        "total_fraction": total,
        "dominant": max(
            (("fees", fee), ("spread", spread), ("slippage", slip)),
            key=lambda kv: kv[1])[0],
    }


def minimum_edge(cost_fraction: float, safety_multiple: float = 2.0) -> float:
    """The gross move a trade must be aiming for to be worth taking.

    The multiple exists because breaking even on costs is not a strategy: a
    trade whose target only just covers its costs has no room for the times
    the estimate is wrong, and estimates of slippage are wrong often. Two is a
    convention, not a result -- it should be set from Trezo's own fill data
    once enough of it exists.
    """
    return float(cost_fraction) * float(safety_multiple)


def viability(target_pct: float, cost: dict,
              safety_multiple: float = 2.0) -> dict:
    """Can this trade plan clear its own costs with room to spare?"""
    try:
        t = float(target_pct)
    except (TypeError, ValueError):
        return {"viable": False, "why": "no target supplied"}
    total = float(cost.get("total_fraction") or 0)
    need = minimum_edge(total, safety_multiple)
    ratio = (t / total) if total > 0 else None
    if total <= 0:
        return {"viable": False,
                "why": "costs unknown -- a zero cost estimate is a missing "
                       "measurement, not a free trade"}
    ok = t >= need
    return {
        "viable": ok,
        "target_pct": round(t * 100, 3),
        "cost_pct": round(total * 100, 3),
        "required_pct": round(need * 100, 3),
        "target_to_cost_ratio": round(ratio, 2) if ratio else None,
        "dominant_cost": cost.get("dominant"),
        "why": (
            f"target {t*100:.2f}% is {ratio:.1f}x round-trip cost "
            f"{total*100:.2f}% (dominated by {cost.get('dominant')}); "
            + ("clears the " f"{safety_multiple:g}x bar" if ok
               else f"BELOW the {safety_multiple:g}x bar of {need*100:.2f}%")
        ) if ratio else "cost or target missing",
    }


def adverse_selection_note(half_spread: Optional[float],
                           fee_bps: float) -> str:
    """A sentence on what the spread is actually charging for.

    Harris's decomposition says part of the spread compensates the other side
    for trading against people who know more. When the spread dwarfs the
    explicit fee, that is what is being paid for -- and it is a signal about
    the venue, not just a number to subtract.
    """
    if not half_spread:
        return ("spread not measured -- the fee is only the part of the cost "
                "that shows up on a statement")
    spread_pct = 2.0 * half_spread * 100
    fee_pct = 2.0 * fee_bps / 100.0
    if fee_pct <= 0:
        return f"round-trip spread {spread_pct:.3f}%, no explicit fee"
    ratio = spread_pct / fee_pct
    if ratio >= 2.0:
        return (f"round-trip spread {spread_pct:.3f}% is {ratio:.1f}x the "
                f"explicit fee {fee_pct:.3f}% -- most of what this trade pays "
                f"is compensation to the other side for the risk that we are "
                f"the better-informed party, which is a statement about how "
                f"thin this market is")
    return (f"round-trip spread {spread_pct:.3f}% versus fee {fee_pct:.3f}% -- "
            f"an ordinary balance for a liquid instrument")
