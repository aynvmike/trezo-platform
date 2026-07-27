"""Portfolio-level financial understanding (Mike 2026-07-27).

"Upgrade the agents to have a deeper understanding of the network and
finance as a whole."

The gap this closes, in one sentence: the book counted 14 positions and
believed it held 14 bets. On 2026-07-27 it held 9 crypto positions that
fell together -- crypto lost $30.82 across three closes while stocks and
forex were flat. Fourteen positions, roughly three independent risks.
Counting POSITIONS is not measuring RISK.

Real portfolio finance says exposure clusters into correlated baskets,
and the honest measure is how many INDEPENDENT bets a book actually
holds -- the diversification ratio. This module gives every agent that
read, and turns it into a decision: the more crowded a basket already
is, the higher the confidence bar for adding to it.

Baskets (single dominant risk factor each):
  crypto      -- BTC beta. Every alt is mostly a leveraged BTC bet.
  equity_beta -- stocks + broad sector ETFs; one market factor.
  usd         -- dollar-driven FX.
  gold, bonds -- the classic diversifiers.
  income      -- covered-call ETFs (equity beta with the upside sold).

Nothing here bans anything -- it prices crowding into the confidence
bar, exactly like regime, goal and margin do. Conditions, never lists.
"""

from __future__ import annotations

import os
from collections import Counter

# Alt-coins are not independent of Bitcoin; sector ETFs are not
# independent of the index. Naming the FACTOR is the whole point.
_GOLD = {"GLD", "IAU", "GDX", "XAUUSD", "GOLD"}
_BONDS = {"TLT", "IEF", "SHY", "AGG", "BND", "LQD", "HYG"}
_INCOME_HINTS = ("YMAX", "JEPI", "JEPQ", "NVDY", "TSLY", "GOOY", "AMZY",
                 "AIYY", "FEPI", "MSFY", "QYLD", "RYLD", "XYLD", "BITO")


def basket_of(ticker: str, asset_type: str = "", strategy: str = "") -> str:
    """Which correlated risk factor this position really belongs to."""
    t = (ticker or "").upper().strip()
    a = (asset_type or "").lower()
    s = (strategy or "").lower()
    if a == "crypto" or s.startswith("crypto"):
        return "crypto"
    if a == "forex" or s.startswith("forex"):
        return "usd"
    if t in _GOLD:
        return "gold"
    if t in _BONDS:
        return "bonds"
    if any(h in t for h in _INCOME_HINTS) or s.startswith(("dividend",
                                                           "yieldmax")):
        return "income"
    return "equity_beta"


def concentration_read(positions: list[dict]) -> dict:
    """How many INDEPENDENT bets does this book actually hold?

    `effective_bets` is a diversification ratio, not a position count:
    a basket of n correlated names counts as roughly sqrt(n) bets --
    the standard intuition that correlated risk adds sub-linearly.
    Ten crypto positions are closer to three bets than to ten.
    """
    if not positions:
        return {"positions": 0, "baskets": {}, "effective_bets": 0.0,
                "dominant": None, "dominant_share": 0.0,
                "concentrated": False}
    b = Counter()
    for p in positions:
        b[basket_of(str(p.get("ticker") or ""),
                    str(p.get("asset_type") or ""),
                    str(p.get("strategy") or ""))] += 1
    n = sum(b.values())
    eff = sum(cnt ** 0.5 for cnt in b.values())
    dom, dom_n = b.most_common(1)[0]
    share = dom_n / float(n)
    return {
        "positions": n,
        "baskets": dict(b),
        "effective_bets": round(eff, 2),
        "dominant": dom,
        "dominant_count": dom_n,
        "dominant_share": round(share, 3),
        # A book is concentrated when one factor owns most of it AND
        # there is enough of it to matter.
        "concentrated": bool(share >= 0.5 and dom_n >= 4),
    }


def crowding_bump(basket: str, read: dict) -> tuple[int, str]:
    """Extra TCS required to add to an already-crowded basket.

    Bounded and small, in line with every other live bump (regime <=
    +15, goal +5, margin +8): +3 once a basket holds 4, +6 at 6, +9 at
    8 or more. The intent is to make the marginal correlated bet EARN
    its place, not to ban the lane that is currently earning.
    """
    try:
        step = int(float(os.getenv("TREZO_CROWDING_STEP", "3")))
        cap = int(float(os.getenv("TREZO_CROWDING_MAX", "9")))
    except (TypeError, ValueError):
        step, cap = 3, 9
    n = int((read.get("baskets") or {}).get(basket, 0))
    if n < 4:
        return 0, ""
    tier = min(cap, step * (1 + (n - 4) // 2))
    return tier, (f", crowding +{tier} ({n} open in the '{basket}' "
                  f"basket - correlated risk, ~"
                  f"{read.get('effective_bets')} independent bets across "
                  f"{read.get('positions')} positions)")


def explain(read: dict) -> str:
    """One human-readable line for the feed / digest."""
    if not read.get("positions"):
        return "Book empty."
    parts = ", ".join(f"{k} {v}" for k, v in
                      sorted((read.get("baskets") or {}).items(),
                             key=lambda kv: -kv[1]))
    line = (f"{read['positions']} positions across {parts} = about "
            f"{read['effective_bets']} independent bets.")
    if read.get("concentrated"):
        line += (f" CONCENTRATED: {read['dominant_share']:.0%} of the book "
                 f"is one risk factor ('{read['dominant']}') - it will "
                 f"win together and lose together.")
    return line
