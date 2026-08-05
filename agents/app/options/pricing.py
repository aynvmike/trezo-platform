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


# =====================================================================
# RANGE-BASED VOLATILITY ESTIMATORS (2026-08-05)
# ---------------------------------------------------------------------
# Source: Euan Sinclair, "Volatility Trading" 2nd ed. (Wiley) — the
# volatility-estimation chapter. Distilled in the knowledge library as
# SINCLAIR_MEASURING_VOLATILITY.md.
#
# The problem: estimate_iv() above uses close-to-close returns, which is
# the LEAST efficient estimator available. It sees one number per bar and
# discards the intrabar range entirely — a day that opens at 100, runs to
# 108, falls to 96 and closes at 100 registers as ZERO movement.
#
# Range-based estimators read the high and low, which Trezo already
# fetches on every candle and currently throws away. They extract several
# times more information from the same bars, giving a far more stable
# estimate from a shorter window.
#
# Implemented here (each handles one more real-world effect than the last):
#   Parkinson       — uses high/low. Assumes no drift, no gaps.
#   Garman-Klass    — adds open/close. More efficient again.
#   Rogers-Satchell — handles a drifting (trending) price properly.
#   Yang-Zhang      — adds overnight gaps; the best all-round choice, and
#                     the right default for a book holding crypto (24/7,
#                     wide intrabar ranges) and gapping stocks.
#
# All return ANNUALISED volatility, matching estimate_iv()'s contract, and
# all fail safe: any bad input falls back to the close-to-close number so
# a data hiccup can never leave a caller without a volatility.
# =====================================================================

_TRADING_PERIODS = 252


def _ann(var_per_period: float, periods: int = _TRADING_PERIODS) -> float:
    """Annualise a per-period variance and clamp to the same sane band
    estimate_iv() uses, so every estimator is interchangeable."""
    if var_per_period <= 0:
        return 0.0
    return max(0.15, min(2.0, math.sqrt(var_per_period * periods)))


def parkinson_vol(candles: list, periods: int = _TRADING_PERIODS) -> float:
    """High-low estimator. ~5x more efficient than close-to-close."""
    try:
        vals = []
        for c in candles:
            hi, lo = float(c.high), float(c.low)
            if hi > 0 and lo > 0 and hi >= lo:
                vals.append(math.log(hi / lo) ** 2)
        if len(vals) < 2:
            return 0.0
        var = sum(vals) / (4.0 * math.log(2.0) * len(vals))
        return _ann(var, periods)
    except Exception:  # noqa: BLE001
        return 0.0


def garman_klass_vol(candles: list, periods: int = _TRADING_PERIODS) -> float:
    """High-low-open-close estimator. More efficient than Parkinson."""
    try:
        vals = []
        for c in candles:
            hi, lo, op, cl = (float(c.high), float(c.low),
                              float(c.open), float(c.close))
            if min(hi, lo, op, cl) <= 0 or hi < lo:
                continue
            hl = math.log(hi / lo) ** 2
            co = math.log(cl / op) ** 2
            vals.append(0.5 * hl - (2.0 * math.log(2.0) - 1.0) * co)
        if len(vals) < 2:
            return 0.0
        return _ann(sum(vals) / len(vals), periods)
    except Exception:  # noqa: BLE001
        return 0.0


def rogers_satchell_vol(candles: list, periods: int = _TRADING_PERIODS) -> float:
    """Handles a trending (drifting) price, which Parkinson and
    Garman-Klass assume away. Important for names in a strong move."""
    try:
        vals = []
        for c in candles:
            hi, lo, op, cl = (float(c.high), float(c.low),
                              float(c.open), float(c.close))
            if min(hi, lo, op, cl) <= 0 or hi < lo:
                continue
            vals.append(math.log(hi / cl) * math.log(hi / op)
                        + math.log(lo / cl) * math.log(lo / op))
        if len(vals) < 2:
            return 0.0
        return _ann(sum(vals) / len(vals), periods)
    except Exception:  # noqa: BLE001
        return 0.0


def yang_zhang_vol(candles: list, periods: int = _TRADING_PERIODS) -> float:
    """Best all-round: drift-independent AND it prices the overnight gap,
    which the others ignore. Trezo gaps constantly (open-bell moves on
    stocks; venue gaps on crypto), so this is the right default."""
    try:
        n = len(candles)
        if n < 3:
            return 0.0
        overnight, openclose = [], []
        for i in range(1, n):
            p_cl = float(candles[i - 1].close)
            op, cl = float(candles[i].open), float(candles[i].close)
            if min(p_cl, op, cl) <= 0:
                continue
            overnight.append(math.log(op / p_cl))    # gap from prior close
            openclose.append(math.log(cl / op))      # the session itself
        m = len(overnight)
        if m < 2:
            return 0.0
        mo = sum(overnight) / m
        mc = sum(openclose) / m
        v_o = sum((x - mo) ** 2 for x in overnight) / (m - 1)
        v_c = sum((x - mc) ** 2 for x in openclose) / (m - 1)
        # Rogers-Satchell variance over the same bars (already annualised
        # by the helper, so undo that to combine variances correctly).
        rs_ann = rogers_satchell_vol(candles[1:], periods)
        v_rs = (rs_ann ** 2) / periods if rs_ann > 0 else 0.0
        k = 0.34 / (1.34 + (m + 1) / (m - 1))
        var = v_o + k * v_c + (1.0 - k) * v_rs
        return _ann(var, periods)
    except Exception:  # noqa: BLE001
        return 0.0


_ESTIMATORS = {
    "yang_zhang": yang_zhang_vol,
    "garman_klass": garman_klass_vol,
    "rogers_satchell": rogers_satchell_vol,
    "parkinson": parkinson_vol,
}


def estimate_vol_from_candles(candles: list, estimator: str = "",
                              periods: int = _TRADING_PERIODS) -> dict:
    """Annualised volatility from OHLC bars, using a range-based estimator.

    Returns {"vol", "estimator", "close_to_close", "candles"} so callers
    can log BOTH the new and old numbers side by side — per Trezo's rule
    that a change earns its place with evidence, not assertion.

    Falls back to close-to-close automatically if the range estimate
    cannot be computed (missing OHLC, too few bars, bad data)."""
    cc = 0.0
    try:
        closes = [float(c.close) for c in candles]
        cc = estimate_iv(daily_returns_from_closes(closes))
    except Exception:  # noqa: BLE001
        cc = 0.40
    if not estimator:
        try:
            from app.config import get_settings
            estimator = str(getattr(get_settings(),
                                    "trezo_vol_estimator", "yang_zhang"))
        except Exception:  # noqa: BLE001
            estimator = "yang_zhang"
    fn = _ESTIMATORS.get(estimator, yang_zhang_vol)
    v = fn(candles, periods)
    if v <= 0:                      # estimator could not run -> old way
        return {"vol": cc, "estimator": "close_to_close",
                "close_to_close": cc, "candles": len(candles)}
    return {"vol": v, "estimator": estimator,
            "close_to_close": cc, "candles": len(candles)}


def iv_from_candles(candles: list, lookback: int = 60) -> float:
    """The one call every strategy should use for volatility.

    Uses the range-based estimator (high/low data Trezo already has) and
    falls back to close-to-close automatically. Logs both numbers the
    first time a symbol is seen each session so the improvement is
    evidenced rather than asserted — Trezo's standing rule.
    """
    try:
        window = candles[-lookback:] if lookback else candles
        r = estimate_vol_from_candles(window)
        v, cc = float(r.get("vol") or 0), float(r.get("close_to_close") or 0)
        if v > 0 and cc > 0 and abs(v - cc) / max(cc, 1e-9) > 0.15:
            # Materially different from the old method -- worth recording.
            try:
                from app.agents.activity_log import record as _vrec
                _vrec("vol_estimator", "SYSTEM",
                      reason=(f"{r.get('estimator')} vol {v*100:.1f}% vs "
                              f"close-to-close {cc*100:.1f}% over "
                              f"{r.get('candles')} bars"),
                      extra={"estimator": r.get("estimator"),
                             "vol": round(v, 4), "close_to_close": round(cc, 4)})
            except Exception:  # noqa: BLE001
                pass
        return v if v > 0 else (cc if cc > 0 else 0.40)
    except Exception:  # noqa: BLE001
        try:
            return estimate_iv(daily_returns_from_closes(
                [float(c.close) for c in candles[-lookback:]]))
        except Exception:  # noqa: BLE001
            return 0.40
