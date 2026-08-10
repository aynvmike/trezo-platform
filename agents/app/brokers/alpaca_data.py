"""Alpaca market-data client — live quotes and bars.

Data feed, Part 1. The trading client (alpaca.py) hits the paper-trading
API; this one hits Alpaca's market-data API for real bid/ask quotes and
price bars. It uses the same API keys, and the free IEX feed by default.

Best-effort: with no keys, or on any error, every function returns None /
{} so callers fall back to Trezo's modeled data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.brokers.alpaca import alpaca_configured, _headers, _base_url

DATA_BASE_URL = "https://data.alpaca.markets"
DATA_FEED = "iex"        # free tier; "sip" needs a paid Alpaca subscription


@dataclass
class Quote:
    symbol: str
    bid: float
    ask: float
    bid_size: float
    ask_size: float
    ts: str

    @property
    def mid(self) -> float:
        if self.bid > 0 and self.ask > 0:
            return (self.bid + self.ask) / 2.0
        return 0.0

    @property
    def spread_pct(self) -> float:
        m = self.mid
        return ((self.ask - self.bid) / m) if m > 0 else 0.0


def market_data_available() -> bool:
    """True when the Alpaca keys needed for the data feed are configured."""
    return alpaca_configured()


async def _data_get(path: str, params: Optional[dict] = None):
    """GET an Alpaca market-data endpoint. Parsed JSON, or None on failure."""
    if not alpaca_configured():
        return None
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(DATA_BASE_URL + path,
                                    headers=_headers(), params=params or {})
            resp.raise_for_status()
            return resp.json()
    except Exception:  # noqa: BLE001
        return None


def _quote_from_raw(symbol: str, q: dict) -> Quote:
    def f(k: str) -> float:
        try:
            return float(q.get(k) or 0)
        except (TypeError, ValueError):
            return 0.0
    return Quote(symbol=symbol.upper(), bid=f("bp"), ask=f("ap"),
                 bid_size=f("bs"), ask_size=f("as"), ts=str(q.get("t") or ""))


async def get_quote(symbol: str) -> Optional[Quote]:
    """Latest bid/ask for one stock symbol. None if unavailable."""
    sym = symbol.upper()
    data = await _data_get("/v2/stocks/quotes/latest",
                           {"symbols": sym, "feed": DATA_FEED})
    if not isinstance(data, dict):
        return None
    q = (data.get("quotes") or {}).get(sym)
    return _quote_from_raw(sym, q) if isinstance(q, dict) else None


async def get_crypto_quote(symbol: str) -> Optional[Quote]:
    """Latest bid/ask for one crypto pair. None if unavailable.

    Added 2026-08-05 (Harris, phase 4). Until now Trezo had quote
    functions for stocks and for options but NONE for crypto, so the
    crypto spread was never observed at all -- while the cost model
    assumed a flat 5bps of slippage for every asset. The crypto scalp
    lane exits the moment a gain covers modelled round-trip cost, so
    that unmeasured number was setting the exit for the whole lane.

    Alpaca expects the pair form BTC/USD, so a bare ticker is expanded.
    """
    sym = symbol.upper().strip()
    if "/" not in sym:
        sym = f"{sym}/USD"
    data = await _data_get("/v1beta3/crypto/us/latest/quotes", {"symbols": sym})
    if not isinstance(data, dict):
        return None
    q = (data.get("quotes") or {}).get(sym)
    return _quote_from_raw(sym, q) if isinstance(q, dict) else None


async def get_quotes(symbols: list[str]) -> dict[str, Quote]:
    """Latest bid/ask for several stock symbols in one call."""
    syms = [s.upper() for s in symbols if s]
    if not syms:
        return {}
    data = await _data_get("/v2/stocks/quotes/latest",
                           {"symbols": ",".join(syms), "feed": DATA_FEED})
    out: dict[str, Quote] = {}
    if isinstance(data, dict):
        for sym, q in (data.get("quotes") or {}).items():
            if isinstance(q, dict):
                out[sym.upper()] = _quote_from_raw(sym, q)
    return out


async def get_latest_bar(symbol: str) -> Optional[dict]:
    """Latest price bar for a stock — {o,h,l,c,v,t}. None if unavailable."""
    sym = symbol.upper()
    data = await _data_get("/v2/stocks/bars/latest",
                           {"symbols": sym, "feed": DATA_FEED})
    if not isinstance(data, dict):
        return None
    bar = (data.get("bars") or {}).get(sym)
    return bar if isinstance(bar, dict) else None


# --- Options data (Data feed Part 2) -----------------------------------

@dataclass
class LiveOption:
    occ: str
    strike: float
    expiration: str         # ISO date
    premium: float          # per-share mid price


async def _trading_get(path: str, params: Optional[dict] = None):
    """GET an Alpaca trading-API endpoint (options contracts live here)."""
    if not alpaca_configured():
        return None
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(_base_url() + path,
                                    headers=_headers(), params=params or {})
            resp.raise_for_status()
            return resp.json()
    except Exception:  # noqa: BLE001
        return None


async def get_option_contracts(underlying: str, option_type: str,
                                exp_lo: str, exp_hi: str,
                                strike_lo: float, strike_hi: float,
                                limit: int = 100) -> list[dict]:
    """Real listed option contracts for an underlying, filtered by a
    strike and expiration window. [] if none / unavailable."""
    typ = "call" if str(option_type).lower().startswith("c") else "put"
    data = await _trading_get("/v2/options/contracts", {
        "underlying_symbols": underlying.upper(),
        "type": typ,
        "expiration_date_gte": exp_lo,
        "expiration_date_lte": exp_hi,
        "strike_price_gte": str(strike_lo),
        "strike_price_lte": str(strike_hi),
        "status": "active",
        "limit": str(limit),
    })
    if isinstance(data, dict):
        c = data.get("option_contracts")
        return c if isinstance(c, list) else []
    return []


async def get_option_quote(occ_symbol: str) -> Optional[float]:
    """Latest mid premium for one option contract (OCC symbol). None if
    unavailable. Uses the free 'indicative' options feed."""
    data = await _data_get("/v1beta1/options/quotes/latest",
                           {"symbols": occ_symbol, "feed": "indicative"})
    if not isinstance(data, dict):
        return None
    q = (data.get("quotes") or {}).get(occ_symbol)
    if not isinstance(q, dict):
        return None
    try:
        bid = float(q.get("bp") or 0)
        ask = float(q.get("ap") or 0)
    except (TypeError, ValueError):
        return None
    if bid > 0 and ask > 0:
        return round((bid + ask) / 2.0, 4)
    if ask > 0:
        return round(ask, 4)
    return None


async def live_option_pick(underlying: str, option_type: str,
                            target_strike: float,
                            target_exp_iso: str) -> Optional[LiveOption]:
    """Find the real listed contract nearest a target strike + expiration
    and return it with a live mid premium. None on any miss - callers then
    fall back to the modeled Black-Scholes price."""
    if not alpaca_configured():
        return None
    from datetime import date, timedelta
    try:
        target_exp = date.fromisoformat(str(target_exp_iso)[:10])
    except Exception:  # noqa: BLE001
        return None

    exp_lo = (target_exp - timedelta(days=12)).isoformat()
    exp_hi = (target_exp + timedelta(days=12)).isoformat()
    strike_lo = round(float(target_strike) * 0.85, 2)
    strike_hi = round(float(target_strike) * 1.15, 2)

    contracts = await get_option_contracts(
        underlying, option_type, exp_lo, exp_hi, strike_lo, strike_hi)
    if not contracts:
        return None

    def _score(c: dict):
        try:
            cs = float(c.get("strike_price") or 0)
            ce = date.fromisoformat(str(c.get("expiration_date"))[:10])
        except Exception:  # noqa: BLE001
            return (9e9, 9e9)
        return (abs(cs - float(target_strike)), abs((ce - target_exp).days))

    best = min(contracts, key=_score)
    occ = best.get("symbol")
    if not occ:
        return None
    premium = await get_option_quote(str(occ))
    if premium is None or premium <= 0:
        return None
    try:
        return LiveOption(
            occ=str(occ),
            strike=float(best.get("strike_price") or 0),
            expiration=str(best.get("expiration_date"))[:10],
            premium=premium,
        )
    except Exception:  # noqa: BLE001
        return None


async def get_daily_bars(symbol: str, lookback_days: int = 140) -> list:
    """Daily OHLCV bars for a stock via Alpaca. Returns raw bar dicts
    ({t,o,h,l,c,v}), or [] when unavailable. Daily bars skip weekends, so
    the calendar window is widened to land ~lookback_days trading bars.
    """
    if not alpaca_configured():
        return []
    from datetime import datetime, timedelta, timezone
    cal_days = int(lookback_days * 1.5) + 14
    start = (datetime.now(timezone.utc)
             - timedelta(days=cal_days)).strftime("%Y-%m-%d")
    data = await _data_get(f"/v2/stocks/{symbol.upper()}/bars", {
        "timeframe": "1Day",
        "start": start,
        "limit": 10000,
        "feed": DATA_FEED,
        "adjustment": "raw",
    })
    if not isinstance(data, dict):
        return []
    bars = data.get("bars")
    return bars if isinstance(bars, list) else []


async def get_most_actives(top: int = 25, by: str = "trades") -> list[str]:
    """Most-active stocks -- the LIQUID end of today's tape (2026-07-02).

    RANKED BY TRADE COUNT, NOT SHARE VOLUME (changed 2026-08-10).

    Share volume is price-inverted: a $2 stock printing 50M shares
    outranks AAPL printing 40M, so `by=volume` systematically puts penny
    stocks at the FRONT of the "most liquid" list and the real names at
    the back. Measured live on 2026-08-10:

        by=volume  SOAR, SCKT, YYAI, AUUD, MSTU, SPCX, RCON, ACHR ...
        by=trades  NVDA, SPCX, JWEL, STKH, AAPL, TSLA, INTC, PLTR, MSFT

        SOAR: 289,992,648 shares in   229,812 trades
        NVDA:  75,486,505 shares in 1,963,091 trades

    Trade count is price-independent -- it counts how many times the
    market actually changed hands, which is what decides whether an order
    fills without moving the price. That is the property the scan pool
    needs, and the property the liquidity gate downstream tests for.

    This was the cause of the 2026-08-10 "agents aren't trading stocks"
    report: 94% of stock vetoes were the volume floor rejecting names the
    pool should never have surfaced (VREX, YJ, SOAR at 15k-58k average
    volume against a 100k minimum). The gates were right; the pool fed
    them names that could not pass. Same code on 8/4 happened to surface
    AMZN/AMAT/NVDA -- the ranking is simply unstable.

    `by` stays a parameter so "volume" remains available for anything
    that genuinely wants share-count ordering. Empty list on any failure.
    """
    try:
        data = await _data_get("/v1beta1/screener/stocks/most-actives",
                               {"by": str(by or "trades"), "top": str(int(top))})
    except Exception:  # noqa: BLE001
        return []
    rows = (data or {}).get("most_actives", []) if isinstance(data, dict) else []
    out: list[str] = []
    for r in rows:
        sym = str((r or {}).get("symbol", "")).upper().strip()
        if sym:
            out.append(sym)
    return out


async def get_market_movers(top: int = 25) -> dict:
    """Today's biggest stock gainers and losers — Alpaca's movers screener.

    Returns {"gainers": [...], "losers": [...]} where each entry is a dict
    {symbol, price, change, percent_change}. {} when unavailable. Uses the
    same Alpaca keys as the rest of the data feed — no extra subscription.
    """
    data = await _data_get("/v1beta1/screener/stocks/movers", {"top": str(top)})
    if not isinstance(data, dict):
        return {}
    out: dict = {}
    for side in ("gainers", "losers"):
        rows = data.get(side)
        if not isinstance(rows, list):
            continue
        out[side] = []
        for r in rows:
            sym = str(r.get("symbol", "")).upper().strip()
            if not sym:
                continue
            def _f(k: str) -> float:
                try:
                    return float(r.get(k) or 0)
                except (TypeError, ValueError):
                    return 0.0
            out[side].append({
                "symbol": sym,
                "price": _f("price"),
                "change": _f("change"),
                "percent_change": _f("percent_change"),
            })
    return out
