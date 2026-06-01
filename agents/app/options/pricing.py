"""Black-Scholes options pricing — MODELED, not live market data.

Trezo has no options-chain feed yet (free tiers don't provide reliable
options data). This module prices options with the Black-Scholes-Merton
model so the Dividend Wheel and options strategies have something
realistic to work against.

IMPORTANT: every premium produced here is a *model estimate*, and the
fallback used when no live feed is reachable. The Wheel now prefers a
live Alpaca options quote when one is available (see refine_csp_live in
app/strategies/wheel.py); this model is what it falls back to.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Risk-free rate assumption (~3-month T-bill territory). Configurable later.
RISK_FREE_RATE = 0.043


def _norm_cdf(x: float) -> float:
    """Standard normal CDF via the error function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    """Standard normal probability density."""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


@dataclass
class OptionQuote:
    option_type: str      # 'call' | 'put'
    underlying: float
    strike: float
    days_to_expiry: int
    iv: float             # annualized implied volatility (decimal, e.g. 0.45)
    premium: float        # per-share price; contract = premium * 100
    delta: float          # per-share Greeks (delta, gamma);
    gamma: float
    theta: float          # theta per calendar day, per share
    vega: float           # vega per 1% (1 point) of IV, per share


def estimate_iv(daily_returns: list[float]) -> float:
    """Annualized volatility from recent daily returns — our IV proxy.

    Black-Scholes wants implied vol; without an options market to imply it
    from, we use realized volatility (stdev of daily returns × √252) as a
    stand-in. Clamped to a sane 15%-200% band.
    """
    if len(daily_returns) < 2:
        return 0.40
    n = len(daily_returns)
    mean = sum(daily_returns) / n
    var = sum((r - mean) ** 2 for r in daily_returns) / (n - 1)
    daily_vol = math.sqrt(var)
    annual = daily_vol * math.sqrt(252)
    return max(0.15, min(2.0, annual))


def theoretical_price(
    option_type: str,
    underlying: float,
    strike: float,
    days_to_expiry: int,
    iv: float,
    risk_free: float = RISK_FREE_RATE,
) -> OptionQuote:
    """Black-Scholes-Merton price for a European option.

    American-style early exercise isn't modeled — fine for the
    short-dated, mostly-held-to-expiry strategies Trezo runs.
    """
    S = max(underlying, 0.0001)
    K = max(strike, 0.0001)
    T = max(days_to_expiry, 1) / 365.0
    sigma = max(iv, 0.01)

    d1 = (math.log(S / K) + (risk_free + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    sqrt_t = sigma * math.sqrt(T)
    pdf_d1 = _norm_pdf(d1)
    disc = K * math.exp(-risk_free * T)

    if option_type == "call":
        premium = S * _norm_cdf(d1) - disc * _norm_cdf(d2)
        delta = _norm_cdf(d1)
        theta_annual = (-(S * pdf_d1 * sigma) / (2.0 * math.sqrt(T))
                        - risk_free * disc * _norm_cdf(d2))
    else:  # put
        premium = disc * _norm_cdf(-d2) - S * _norm_cdf(-d1)
        delta = _norm_cdf(d1) - 1.0
        theta_annual = (-(S * pdf_d1 * sigma) / (2.0 * math.sqrt(T))
                        + risk_free * disc * _norm_cdf(-d2))

    # gamma and vega are the same for calls and puts.
    gamma = pdf_d1 / (S * sqrt_t) if sqrt_t > 0 else 0.0
    vega = S * pdf_d1 * math.sqrt(T) / 100.0      # per 1% IV move
    theta = theta_annual / 365.0                  # per calendar day

    return OptionQuote(
        option_type=option_type,
        underlying=S,
        strike=K,
        days_to_expiry=days_to_expiry,
        iv=sigma,
        premium=max(0.0, round(premium, 4)),
        delta=round(delta, 4),
        gamma=round(gamma, 6),
        theta=round(theta, 4),
        vega=round(vega, 4),
    )


def daily_returns_from_closes(closes: list[float]) -> list[float]:
    """Convert a close-price series into daily simple returns."""
    out: list[float] = []
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        if prev > 0:
            out.append((closes[i] - prev) / prev)
    return out
