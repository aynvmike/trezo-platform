"""The Dividend Wheel — cash-secured puts → covered calls cycle.

Spec (TREZO_STRATEGY_RULES.md §3): a conservative income strategy.
  1. Sell a cash-secured put (CSP) on a quality stock you'd be happy to own.
  2. If assigned, you own 100 shares at the strike. If not, keep the premium
     and repeat.
  3. Once holding shares, sell a covered call (CC) above your cost basis.
  4. If called away, keep premium + any gain. Repeat from step 1.

Trezo runs the Wheel on a small set of quality dividend names. Strikes are
chosen near the ~0.30 delta level — far enough out-of-the-money to rarely
assign, close enough to collect meaningful premium.

Premiums are MODELED (Black-Scholes) — see app/options/pricing.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from app.options.pricing import OptionQuote, theoretical_price, estimate_iv, daily_returns_from_closes
from app.patterns import Candle

# Quality names suited to the Wheel - diverse dividend payers with
# liquid options markets. Mike 2026-06-01: blue-chip-only is too
# narrow + too cash-expensive per CSP. The mix below trades across
# price tiers, sectors, and IV regimes so the bot can deploy more
# contracts per dollar AND collect varied premium.
#
# Tier A (REITs/BDCs, cash-efficient, high yield, active premium):
#   O    - Realty Income       (~$60, ~5.5% monthly REIT)
#   MAIN - Main Street Capital (~$55, ~6.0% BDC)
#   STAG - STAG Industrial     (~$35, ~4.5% industrial REIT)
#   NLY  - Annaly Capital      (~$20, ~13%  mortgage REIT)
#   ARCC - Ares Capital        (~$23, ~9%   BDC)
#
# Tier B (cheap CSPs, high yield, predictable):
#   F    - Ford                (~$11, 6.0%)
#   T    - AT&T                (~$22, 6.5%)
#   KMI  - Kinder Morgan       (~$20, 6.0% midstream)
#   VZ   - Verizon             (~$40, 6.5%)
#   MO   - Altria              (~$45, 8.0%)
#   INTC - Intel               (~$20, 1.5%)
#
# Tier C (mid-cap dividends, varied IV):
#   PFE  - Pfizer              (~$28, 6.0% pharma)
#   KHC  - Kraft Heinz         (~$30, 5.0% consumer)
#   CSCO - Cisco               (~$50, 3.0% tech)
#   BMY  - Bristol Myers       (~$50, 4.5% pharma)
#   KEY  - KeyCorp             (~$15, 5.0% bank)
#   HPQ  - HP Inc              (~$35, 3.0% tech)
WHEEL_WATCHLIST = [
    # Tier A - REIT / BDC
    "O", "MAIN", "STAG", "NLY", "ARCC",
    # Tier B - cheap CSPs, high yield
    "F", "T", "KMI", "VZ", "MO", "INTC",
    # Tier C - mid-cap dividends
    "PFE", "KHC", "CSCO", "BMY", "KEY", "HPQ",
]

# Target days-to-expiry for each new option (≈ monthly cycle).
TARGET_DTE = 30
# How far out-of-the-money to place strikes, as a fraction of spot.
CSP_OTM = 0.05   # sell puts 5% below spot
CC_OTM = 0.05    # sell calls 5% above spot


@dataclass
class WheelLeg:
    underlying: str
    leg: str             # 'csp' | 'cc'
    option_type: str     # 'put' | 'call'
    strike: float
    expiration: str      # ISO date
    contracts: int
    premium_per_share: float
    credit_usd: float    # premium_per_share * 100 * contracts
    modeled_iv: float
    cash_secured_usd: float  # for CSP: strike * 100 * contracts
    live: bool = False       # True when priced from a live options quote


def _expiration(dte: int = TARGET_DTE) -> str:
    return (date.today() + timedelta(days=dte)).isoformat()


def evaluate_csp(
    underlying: str,
    candles: list[Candle],
    contracts: int = 1,
) -> Optional[WheelLeg]:
    """Build a cash-secured put for `underlying` from current candles."""
    if len(candles) < 22:
        return None
    spot = float(candles[-1].close)
    if spot <= 0:
        return None

    iv = estimate_iv(daily_returns_from_closes([c.close for c in candles[-60:]]))
    strike = round(spot * (1 - CSP_OTM), 2)
    q: OptionQuote = theoretical_price("put", spot, strike, TARGET_DTE, iv)

    credit = q.premium * 100 * contracts
    if credit <= 0:
        return None

    return WheelLeg(
        underlying=underlying.upper(),
        leg="csp",
        option_type="put",
        strike=strike,
        expiration=_expiration(),
        contracts=contracts,
        premium_per_share=q.premium,
        credit_usd=round(credit, 2),
        modeled_iv=q.iv,
        cash_secured_usd=round(strike * 100 * contracts, 2),
    )


def evaluate_cc(
    underlying: str,
    candles: list[Candle],
    cost_basis: float,
    contracts: int = 1,
    days_until_exdiv: Optional[int] = None,
) -> Optional[WheelLeg]:
    """Build a covered call above the holder's cost basis.

    Phase 13b — dividend-window awareness. When ex-div falls inside
    the contract's life (`days_until_exdiv <= TARGET_DTE`), bump the
    OTM cushion by 50% so the call sits further above spot and is
    less likely to be exercised before ex-div. The goal: keep the
    shares through the dividend record date instead of getting
    called away the day before for $0.50 of extra credit.
    """
    if len(candles) < 22:
        return None
    spot = float(candles[-1].close)
    if spot <= 0:
        return None

    iv = estimate_iv(daily_returns_from_closes([c.close for c in candles[-60:]]))
    # Strike at least 5% above spot AND not below cost basis (don't cap
    # a loss in). When an ex-div date falls inside the contract life,
    # push the cushion to 7.5% so the bot doesn't sell the shares out
    # of the dividend by mistake.
    otm = CC_OTM
    if (
        days_until_exdiv is not None
        and 0 <= days_until_exdiv <= TARGET_DTE
    ):
        otm = CC_OTM * 1.5
    strike = round(max(spot * (1 + otm), cost_basis * 1.01), 2)
    q: OptionQuote = theoretical_price("call", spot, strike, TARGET_DTE, iv)

    credit = q.premium * 100 * contracts
    if credit <= 0:
        return None

    return WheelLeg(
        underlying=underlying.upper(),
        leg="cc",
        option_type="call",
        strike=strike,
        expiration=_expiration(),
        contracts=contracts,
        premium_per_share=q.premium,
        credit_usd=round(credit, 2),
        modeled_iv=q.iv,
        cash_secured_usd=0.0,
    )


async def refine_csp_live(leg: WheelLeg) -> WheelLeg:
    """Replace a modeled CSP's strike / expiry / premium with the nearest
    real, live-quoted contract when the Alpaca options feed is available.

    Returns the leg unchanged on any miss - the modeled Black-Scholes
    price stays the fallback, so the Wheel keeps working with no feed."""
    try:
        from app.brokers.alpaca_data import live_option_pick
        lo = await live_option_pick(leg.underlying, "put",
                                    leg.strike, leg.expiration)
    except Exception:  # noqa: BLE001
        lo = None
    if lo is None or lo.premium <= 0:
        return leg
    credit = lo.premium * 100 * leg.contracts
    return WheelLeg(
        underlying=leg.underlying,
        leg="csp",
        option_type="put",
        strike=lo.strike,
        expiration=lo.expiration,
        contracts=leg.contracts,
        premium_per_share=lo.premium,
        credit_usd=round(credit, 2),
        modeled_iv=leg.modeled_iv,
        cash_secured_usd=round(lo.strike * 100 * leg.contracts, 2),
        live=True,
    )
