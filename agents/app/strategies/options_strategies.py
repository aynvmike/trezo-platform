"""Options strategy builders (#122 — 5 of the spec's 14).

  1. Long Call           — simple bullish directional bet, defined risk
                           (max loss = premium paid).
  2. Bull Call Spread    — buy a call, sell a higher call. Cheaper than a
                           long call, capped upside, defined risk.
  3. Cash-Secured Put    — sell a put, hold cash to cover assignment.
                           Bullish/neutral income (also the Wheel's entry).
  4. Bull Put Spread     — sell a put, buy a lower put. A defined-risk
                           credit spread; keep the credit if price holds.
  5. Iron Condor         — a bull put spread + a bear call spread. Credit
                           strategy that profits when price stays in range.

Premiums and Greeks are MODELED (Black-Scholes) — see app/options/pricing.py.
Strikes are chosen relative to spot. Real strike chains arrive with an
options feed. Phase 12 follow-up: every play now carries net position
Greeks (delta / gamma / theta / vega) so the desk can show what the trade
is actually exposed to.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from app.options.pricing import (
    OptionQuote, theoretical_price, estimate_iv, daily_returns_from_closes,
)
from app.patterns import Candle

TARGET_DTE = 35


@dataclass
class OptionsPlay:
    underlying: str
    strategy: str            # 'long_call' | 'bull_call_spread' | 'cash_secured_put'
    direction: str           # 'bullish' | 'income'
    expiration: str
    contracts: int
    net_premium_usd: float   # +credit / -debit
    max_loss_usd: float
    max_gain_usd: float
    modeled_iv: float
    net_delta: float = 0.0   # position-level Greeks (per the whole trade)
    net_gamma: float = 0.0
    net_theta: float = 0.0   # $/day of time decay
    net_vega: float = 0.0    # $ per 1% move in IV
    legs: list[dict] = field(default_factory=list)
    notes: str = ""


def _exp(dte: int = TARGET_DTE) -> str:
    return (date.today() + timedelta(days=dte)).isoformat()


def _leg(action: str, otype: str, q: OptionQuote) -> dict:
    """A leg dict carrying the premium and per-share Greeks from a quote."""
    return {
        "action": action,            # 'buy' | 'sell'
        "type": otype,               # 'call' | 'put'
        "strike": q.strike,
        "premium": q.premium,
        "delta": q.delta,
        "gamma": q.gamma,
        "theta": q.theta,
        "vega": q.vega,
    }


def _net_greeks(legs: list[dict], contracts: int) -> dict:
    """Position-level net Greeks: the sign-weighted sum across legs, scaled
    to the whole trade (×100 shares per contract × contract count). A bought
    leg is long the Greek, a sold leg is short it."""
    nd = ng = nt = nv = 0.0
    for lg in legs:
        sign = 1.0 if lg.get("action") == "buy" else -1.0
        nd += sign * float(lg.get("delta", 0.0))
        ng += sign * float(lg.get("gamma", 0.0))
        nt += sign * float(lg.get("theta", 0.0))
        nv += sign * float(lg.get("vega", 0.0))
    mult = 100.0 * max(1, contracts)
    return {
        "net_delta": round(nd * mult, 2),
        "net_gamma": round(ng * mult, 4),
        "net_theta": round(nt * mult, 2),
        "net_vega": round(nv * mult, 2),
    }


def build_long_call(underlying: str, candles: list[Candle], contracts: int = 1) -> Optional[OptionsPlay]:
    if len(candles) < 22:
        return None
    spot = float(candles[-1].close)
    if spot <= 0:
        return None
    iv = estimate_iv(daily_returns_from_closes([c.close for c in candles[-60:]]))
    strike = round(spot * 1.02, 2)  # slightly OTM
    q = theoretical_price("call", spot, strike, TARGET_DTE, iv)
    debit = q.premium * 100 * contracts
    if debit <= 0:
        return None
    legs = [_leg("buy", "call", q)]
    return OptionsPlay(
        underlying=underlying.upper(),
        strategy="long_call",
        direction="bullish",
        expiration=_exp(),
        contracts=contracts,
        net_premium_usd=round(-debit, 2),         # debit = money out
        max_loss_usd=round(debit, 2),             # can't lose more than premium
        max_gain_usd=-1.0,                        # theoretically unbounded
        modeled_iv=q.iv,
        legs=legs,
        notes=f"Long call, strike {strike} (~2% OTM), {TARGET_DTE} DTE.",
        **_net_greeks(legs, contracts),
    )


def build_bull_call_spread(underlying: str, candles: list[Candle], contracts: int = 1) -> Optional[OptionsPlay]:
    if len(candles) < 22:
        return None
    spot = float(candles[-1].close)
    if spot <= 0:
        return None
    iv = estimate_iv(daily_returns_from_closes([c.close for c in candles[-60:]]))
    long_strike = round(spot * 1.01, 2)
    short_strike = round(spot * 1.08, 2)
    long_q = theoretical_price("call", spot, long_strike, TARGET_DTE, iv)
    short_q = theoretical_price("call", spot, short_strike, TARGET_DTE, iv)
    net_debit = (long_q.premium - short_q.premium) * 100 * contracts
    if net_debit <= 0:
        return None
    width = (short_strike - long_strike) * 100 * contracts
    legs = [_leg("buy", "call", long_q), _leg("sell", "call", short_q)]
    return OptionsPlay(
        underlying=underlying.upper(),
        strategy="bull_call_spread",
        direction="bullish",
        expiration=_exp(),
        contracts=contracts,
        net_premium_usd=round(-net_debit, 2),
        max_loss_usd=round(net_debit, 2),
        max_gain_usd=round(width - net_debit, 2),
        modeled_iv=long_q.iv,
        legs=legs,
        notes=f"Buy {long_strike} call / sell {short_strike} call. Defined risk, capped upside.",
        **_net_greeks(legs, contracts),
    )


def build_cash_secured_put(underlying: str, candles: list[Candle], contracts: int = 1) -> Optional[OptionsPlay]:
    if len(candles) < 22:
        return None
    spot = float(candles[-1].close)
    if spot <= 0:
        return None
    iv = estimate_iv(daily_returns_from_closes([c.close for c in candles[-60:]]))
    strike = round(spot * 0.95, 2)
    q = theoretical_price("put", spot, strike, TARGET_DTE, iv)
    credit = q.premium * 100 * contracts
    if credit <= 0:
        return None
    cash_secured = strike * 100 * contracts
    legs = [_leg("sell", "put", q)]
    return OptionsPlay(
        underlying=underlying.upper(),
        strategy="cash_secured_put",
        direction="income",
        expiration=_exp(),
        contracts=contracts,
        net_premium_usd=round(credit, 2),         # credit = money in
        max_loss_usd=round(cash_secured - credit, 2),  # if stock -> 0
        max_gain_usd=round(credit, 2),
        modeled_iv=q.iv,
        legs=legs,
        notes=f"Sell {strike} put (~5% OTM). Collect {credit:.0f} credit; "
              f"hold {cash_secured:.0f} cash to cover assignment.",
        **_net_greeks(legs, contracts),
    )


def build_bull_put_spread(underlying: str, candles: list[Candle],
                          contracts: int = 1) -> Optional[OptionsPlay]:
    """A credit spread — sell a put, buy a lower put as the wing."""
    if len(candles) < 22:
        return None
    spot = float(candles[-1].close)
    if spot <= 0:
        return None
    iv = estimate_iv(daily_returns_from_closes([c.close for c in candles[-60:]]))
    short_strike = round(spot * 0.95, 2)     # sell put ~5% OTM
    long_strike = round(spot * 0.90, 2)      # buy put ~10% OTM (the wing)
    short_q = theoretical_price("put", spot, short_strike, TARGET_DTE, iv)
    long_q = theoretical_price("put", spot, long_strike, TARGET_DTE, iv)
    net_credit = (short_q.premium - long_q.premium) * 100 * contracts
    if net_credit <= 0:
        return None
    width = (short_strike - long_strike) * 100 * contracts
    legs = [_leg("sell", "put", short_q), _leg("buy", "put", long_q)]
    return OptionsPlay(
        underlying=underlying.upper(),
        strategy="bull_put_spread",
        direction="income",
        expiration=_exp(),
        contracts=contracts,
        net_premium_usd=round(net_credit, 2),
        max_loss_usd=round(width - net_credit, 2),
        max_gain_usd=round(net_credit, 2),
        modeled_iv=short_q.iv,
        legs=legs,
        notes=f"Sell {short_strike} put / buy {long_strike} put. A credit "
              f"spread - keep the credit if {underlying.upper()} holds above "
              f"{short_strike}; loss is capped at the wing.",
        **_net_greeks(legs, contracts),
    )


def build_bear_call_spread(underlying: str, candles: list[Candle],
                           contracts: int = 1) -> Optional[OptionsPlay]:
    """A credit spread for a falling or capped market — sell a call, buy a
    higher call as the wing (Mike 2026-07-14: the full options menu)."""
    if len(candles) < 22:
        return None
    spot = float(candles[-1].close)
    if spot <= 0:
        return None
    iv = estimate_iv(daily_returns_from_closes([c.close for c in candles[-60:]]))
    short_strike = round(spot * 1.05, 2)     # sell call ~5% OTM
    long_strike = round(spot * 1.10, 2)      # buy call ~10% OTM (the wing)
    short_q = theoretical_price("call", spot, short_strike, TARGET_DTE, iv)
    long_q = theoretical_price("call", spot, long_strike, TARGET_DTE, iv)
    net_credit = (short_q.premium - long_q.premium) * 100 * contracts
    if net_credit <= 0:
        return None
    width = (long_strike - short_strike) * 100 * contracts
    legs = [_leg("sell", "call", short_q), _leg("buy", "call", long_q)]
    return OptionsPlay(
        underlying=underlying.upper(),
        strategy="bear_call_spread",
        direction="income",
        expiration=_exp(),
        contracts=contracts,
        net_premium_usd=round(net_credit, 2),
        max_loss_usd=round(width - net_credit, 2),
        max_gain_usd=round(net_credit, 2),
        modeled_iv=short_q.iv,
        legs=legs,
        notes=f"Sell {short_strike} call / buy {long_strike} call. Keep the "
              f"credit if {underlying.upper()} stays below {short_strike}; "
              f"the long wing caps the loss (this is how a 'naked call' "
              f"thesis is expressed with DEFINED risk).",
        **_net_greeks(legs, contracts),
    )


def build_long_put(underlying: str, candles: list[Candle],
                   contracts: int = 1) -> Optional[OptionsPlay]:
    """Buy a put — the defined-risk bearish play (max loss = the debit)."""
    if len(candles) < 22:
        return None
    spot = float(candles[-1].close)
    if spot <= 0:
        return None
    iv = estimate_iv(daily_returns_from_closes([c.close for c in candles[-60:]]))
    strike = round(spot * 0.98, 2)           # just under the money
    q = theoretical_price("put", spot, strike, TARGET_DTE, iv)
    debit = q.premium * 100 * contracts
    if debit <= 0:
        return None
    legs = [_leg("buy", "put", q)]
    return OptionsPlay(
        underlying=underlying.upper(),
        strategy="long_put",
        direction="bearish",
        expiration=_exp(),
        contracts=contracts,
        net_premium_usd=round(-debit, 2),
        max_loss_usd=round(debit, 2),
        max_gain_usd=round((strike - 0) * 100 * contracts - debit, 2),
        modeled_iv=q.iv,
        legs=legs,
        notes=f"Buy the {strike} put. Profits as {underlying.upper()} falls; "
              f"breakeven {round(strike - q.premium, 2)}; the debit is the "
              f"whole risk.",
        **_net_greeks(legs, contracts),
    )


def build_butterfly(underlying: str, candles: list[Candle],
                    contracts: int = 1) -> Optional[OptionsPlay]:
    """Long call butterfly — buy 1 lower call, sell 2 middle calls, buy 1
    upper call. A cheap pin-the-price play: max profit lands when the
    stock closes AT the middle strike at expiry (Mike 2026-07-14)."""
    if len(candles) < 22:
        return None
    spot = float(candles[-1].close)
    if spot <= 0:
        return None
    iv = estimate_iv(daily_returns_from_closes([c.close for c in candles[-60:]]))
    lo = round(spot * 0.97, 2)
    mid = round(spot, 2)
    hi = round(spot * 1.03, 2)
    ql = theoretical_price("call", spot, lo, TARGET_DTE, iv)
    qm = theoretical_price("call", spot, mid, TARGET_DTE, iv)
    qh = theoretical_price("call", spot, hi, TARGET_DTE, iv)
    debit = (ql.premium - 2 * qm.premium + qh.premium) * 100 * contracts
    if debit <= 0:
        return None                     # a butterfly should always cost a bit
    legs = [
        _leg("buy", "call", ql),
        _leg("sell", "call", qm),
        _leg("sell", "call", qm),
        _leg("buy", "call", qh),
    ]
    max_gain = (mid - lo) * 100 * contracts - debit
    return OptionsPlay(
        underlying=underlying.upper(),
        strategy="butterfly",
        direction="neutral",
        expiration=_exp(),
        contracts=contracts,
        net_premium_usd=round(-debit, 2),
        max_loss_usd=round(debit, 2),
        max_gain_usd=round(max_gain, 2),
        modeled_iv=qm.iv,
        legs=legs,
        notes=f"Butterfly {lo}/{mid}/{hi}: buy the wings, sell 2x the body. "
              f"Max profit if {underlying.upper()} pins {mid} at expiry; "
              f"risk is only the small debit.",
        **_net_greeks(legs, contracts),
    )


def build_iron_condor(underlying: str, candles: list[Candle],
                      contracts: int = 1) -> Optional[OptionsPlay]:
    """A bull put spread + a bear call spread — a range-bound credit play."""
    if len(candles) < 22:
        return None
    spot = float(candles[-1].close)
    if spot <= 0:
        return None
    iv = estimate_iv(daily_returns_from_closes([c.close for c in candles[-60:]]))
    put_short = round(spot * 0.95, 2)
    put_long = round(spot * 0.90, 2)
    call_short = round(spot * 1.05, 2)
    call_long = round(spot * 1.10, 2)
    ps = theoretical_price("put", spot, put_short, TARGET_DTE, iv)
    pl = theoretical_price("put", spot, put_long, TARGET_DTE, iv)
    cs = theoretical_price("call", spot, call_short, TARGET_DTE, iv)
    cl = theoretical_price("call", spot, call_long, TARGET_DTE, iv)
    net_credit = ((ps.premium - pl.premium) + (cs.premium - cl.premium)) * 100 * contracts
    if net_credit <= 0:
        return None
    wing = (put_short - put_long) * 100 * contracts   # both wings equal width
    legs = [
        _leg("sell", "put", ps),
        _leg("buy", "put", pl),
        _leg("sell", "call", cs),
        _leg("buy", "call", cl),
    ]
    return OptionsPlay(
        underlying=underlying.upper(),
        strategy="iron_condor",
        direction="income",
        expiration=_exp(),
        contracts=contracts,
        net_premium_usd=round(net_credit, 2),
        max_loss_usd=round(wing - net_credit, 2),
        max_gain_usd=round(net_credit, 2),
        modeled_iv=ps.iv,
        legs=legs,
        notes=f"Iron condor: sell the {put_short}p / {call_short}c, buy the "
              f"{put_long}p / {call_long}c wings. Profits if {underlying.upper()} "
              f"stays between {put_short} and {call_short}.",
        **_net_greeks(legs, contracts),
    )
