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

import datetime as _dt
from app.options.pricing import OptionQuote, theoretical_price, estimate_iv, daily_returns_from_closes, iv_from_candles
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
    # Tier D - small-account collateral fits (Mike 2026-07-16: "why is
    # Ford the only put?" -- because at ~$5k equity the 25% wheel
    # allowance (~$1.2k) only covered F's $1,250 collateral. These
    # liquid, income-tilted names keep the bench wider than one stock
    # until the account grows into Tiers A-C).
    "AGNC", "NOK", "VALE", "KGC", "PSEC",
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
    decay_projected: bool = False  # True when the CSP strike came from the decay projection (Rulebook 5.4)


def _expiration(dte: int = TARGET_DTE) -> str:
    return (date.today() + timedelta(days=dte)).isoformat()


# --- Rulebook 5.4 / 5.5 (2026-07-17, from Mike's real AIYY lesson) --------
RECOVERY_DISTRESS = 0.15      # 15%+ below basis = recovery-mode evaluation
RECOVERY_MIN_CREDIT = 10.0    # minimum dollars per write worth the cap
DECAYER_MONTHLY = -0.02       # trailing bleed of -2%/mo or worse = decayer


def decay_rate_monthly(candles: list[Candle]) -> float:
    """Trailing price drift per 30 calendar days (negative = decayer).

    Measured over ~3 months of trading days so a reverse split's
    cosmetic level never reads as support - the drift is the truth
    (Rulebook 5.2). Returns 0.0 when there is too little history."""
    if len(candles) < 45:
        return 0.0
    window = min(len(candles), 63)
    a = float(candles[-window].close)
    b = float(candles[-1].close)
    if a <= 0 or b <= 0:
        return 0.0
    cal_days = window * 7.0 / 5.0
    return ((b / a) - 1.0) * (30.0 / cal_days)


def evaluate_csp(
    underlying: str,
    candles: list[Candle],
    contracts: int = 1,
    decay_monthly: float = 0.0,
    dte: int = TARGET_DTE,
) -> Optional[WheelLeg]:
    """Build a cash-secured put for `underlying` from current candles."""
    if len(candles) < 22:
        return None
    spot = float(candles[-1].close)
    if spot <= 0:
        return None

    iv = iv_from_candles(candles)
    strike = round(spot * (1 - CSP_OTM), 2)
    _dp = False
    # Rulebook 5.4 - enter through the put. On a decaying name the
    # quote is cosmetic; project the trailing monthly bleed over the
    # contract's life (25% safety margin) and place the strike at or
    # below where the decay lands, never above it.
    if decay_monthly <= DECAYER_MONTHLY:
        projected = spot * (1.0 + decay_monthly * (dte / 30.0) * 1.25)
        if 0 < projected < strike:
            strike = round(projected, 2)
            _dp = True
    q: OptionQuote = theoretical_price("put", spot, strike, dte, iv)

    credit = q.premium * 100 * contracts
    if credit <= 0:
        return None

    return WheelLeg(
        underlying=underlying.upper(),
        leg="csp",
        option_type="put",
        strike=strike,
        expiration=_expiration(dte),
        contracts=contracts,
        premium_per_share=q.premium,
        credit_usd=round(credit, 2),
        modeled_iv=q.iv,
        cash_secured_usd=round(strike * 100 * contracts, 2),
        decay_projected=_dp,
    )


def evaluate_cc(
    underlying: str,
    candles: list[Candle],
    cost_basis: float,
    contracts: int = 1,
    days_until_exdiv: Optional[int] = None,
    dte: int = TARGET_DTE,
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

    iv = iv_from_candles(candles)
    # Strike at least 5% above spot AND not below cost basis (don't cap
    # a loss in). When an ex-div date falls inside the contract life,
    # push the cushion to 7.5% so the bot doesn't sell the shares out
    # of the dividend by mistake.
    otm = CC_OTM
    if (
        days_until_exdiv is not None
        and 0 <= days_until_exdiv <= dte
    ):
        otm = CC_OTM * 1.5
    strike = round(max(spot * (1 + otm), cost_basis * 1.01), 2)
    q: OptionQuote = theoretical_price("call", spot, strike, dte, iv)

    credit = q.premium * 100 * contracts
    if credit <= 0:
        return None

    return WheelLeg(
        underlying=underlying.upper(),
        leg="cc",
        option_type="call",
        strike=strike,
        expiration=_expiration(dte),
        contracts=contracts,
        premium_per_share=q.premium,
        credit_usd=round(credit, 2),
        modeled_iv=q.iv,
        cash_secured_usd=0.0,
    )


def evaluate_cc_recovery(
    underlying: str,
    candles: list[Candle],
    cost_basis: float,
    contracts: int = 1,
    decay_monthly: float = 0.0,
    days_until_exdiv: Optional[int] = None,
    dte: int = TARGET_DTE,
) -> Optional[WheelLeg]:
    """Rulebook 5.5 - the arithmetic gate for UNDERWATER holdings.

    No symbol bans, ever. A recovery-mode covered call may sit BELOW
    cost basis, but only when the math clears:
      1. OTM only - strike above spot, so assignment (strike + premium
         + income already collected) strictly beats selling at today's
         mark. ATM/ITM writes on an underwater hold are forbidden.
      2. Income pace beats decay pace - premium per month must exceed
         the trailing monthly bleed on the lot, or the hole never
         closes and the write is refused.
      3. Premium non-trivial - at least $10 and 0.2% of lot value.
    The caller logs the recovery ledger; the ledger decides continuation.
    """
    if len(candles) < 22:
        return None
    spot = float(candles[-1].close)
    if spot <= 0 or cost_basis <= 0:
        return None
    iv = iv_from_candles(candles)
    otm = CC_OTM
    if days_until_exdiv is not None and 0 <= days_until_exdiv <= dte:
        otm = CC_OTM * 1.5
    strike = round(spot * (1 + otm), 2)   # above SPOT - not basis
    q: OptionQuote = theoretical_price("call", spot, strike, dte, iv)
    credit = q.premium * 100 * contracts
    lot_value = spot * 100 * contracts
    if credit < max(RECOVERY_MIN_CREDIT, lot_value * 0.002):
        return None                        # gate 3: not worth the cap
    income_month = credit * (30.0 / max(dte, 7))
    decay_month = abs(min(decay_monthly, 0.0)) * lot_value
    if decay_month > 0 and income_month <= decay_month:
        return None                        # gate 2: decay outruns income
    return WheelLeg(
        underlying=underlying.upper(),
        leg="cc",
        option_type="call",
        strike=strike,
        expiration=_expiration(dte),
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
    # VARIANCE PREMIUM (Natenberg, phase 3, 2026-08-05). This is the one
    # moment in the wheel where BOTH numbers exist: the real market premium
    # and the realized volatility the model used. Backing the market price
    # out to an implied vol and comparing the two says whether Trezo is being
    # paid more than the stock's own behaviour justifies -- which is the only
    # durable edge in selling premium, and which nothing currently measures.
    #
    # Note what this does NOT fix: the go/no-go decision was already made in
    # evaluate_csp on the MODELED premium, and modeled_iv is carried forward
    # below unchanged. So today this only observes. Acting on it is a
    # behaviour change and belongs in a proposal.
    try:
        from app.options.vol_edge import implied_vol_from_price, premium_verdict
        from app.agents.activity_log import record as _arec
        _dte = max(1, (lo.expiration - _dt.date.today()).days
                   if hasattr(lo.expiration, "year") else 30)
        _real_iv = implied_vol_from_price("put", float(lo.premium),
                                          float(leg.strike), float(lo.strike),
                                          int(_dte))
        _v = premium_verdict(_real_iv, float(leg.modeled_iv or 0))
        _arec("variance_premium", str(leg.underlying), strategy="wheel_csp",
              reason=(f"{_v['verdict']}: {_v['why']}")[:300],
              extra={"real_premium": float(lo.premium),
                     "implied_vol": _real_iv,
                     "realized_vol": float(leg.modeled_iv or 0),
                     "verdict": _v["verdict"],
                     "sell_premium_ok": _v["sell_premium_ok"],
                     "observe_only": True})
    except Exception:  # noqa: BLE001
        pass
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
        decay_projected=getattr(leg, "decay_projected", False),
    )
