"""Candle data fetchers.

- Crypto (XRP/ETH/SOL/BTC): CoinGecko `/coins/{id}/ohlc` (free, no key).
- Stocks (daily): Alpaca market-data bars when Alpaca is configured -
  reliable, and the user already has Alpaca keys - falling back to
  yfinance. Intraday intervals use yfinance.

Returns lists of `Candle` objects sorted oldest -> newest.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

import httpx

from app.patterns import Candle


# CoinGecko ids — the core layer-1 picks plus the ISO 20022-aligned
# coin cluster (Mike 2026-05-31). Building on the ISO 20022 payments
# foundation means the crypto side should at minimum BE AWARE of the
# coins the institutional-payments narrative names. Risk rules still
# apply per coin - thinner names get wider stops via
# `app.data.iso20022_coins.default_params_for`.
from app.data.iso20022_coins import ISO20022_COIN_MAP as _ISO20022_COIN_MAP

COIN_MAP: dict[str, str] = {
    # Core layer-1 picks (kept for broader market context).
    "ETH": "ethereum",
    "SOL": "solana",
    "BTC": "bitcoin",
    # ISO 20022-aligned cluster - see app/data/iso20022_coins.py
    **_ISO20022_COIN_MAP,
}

# Period string -> approximate trading-day count.
_PERIOD_DAYS: dict[str, int] = {
    "1d": 2, "5d": 7, "1mo": 32, "3mo": 100, "6mo": 190,
    "1y": 370, "2y": 740, "5y": 1850, "ytd": 220, "max": 2200,
}


def _period_to_days(period: str) -> int:
    return _PERIOD_DAYS.get(period, 120)


async def fetch_kraken_ohlc(symbol: str, interval_minutes: int = 1440) -> list[Candle]:
    """LIVE daily OHLC from Kraken's PUBLIC OHLC endpoint (no auth, no funds).
    Returns Candles WITH real volume (CoinGecko OHLC carries none, which left
    the SCALP/SWING volume checks blind). Empty list if the coin is not on
    Kraken or the call fails, so the caller falls back to CoinGecko.
    Crypto Part 3 (2026-06-13)."""
    try:
        from app.brokers.crypto_exchange import kraken_pair
        pair = kraken_pair(symbol)
    except Exception:  # noqa: BLE001
        pair = None
    if not pair:
        return []
    url = "https://api.kraken.com/0/public/OHLC"
    params = {"pair": pair, "interval": str(interval_minutes)}
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            r = await client.get(url, params=params)
            if r.status_code != 200:
                return []
            data = r.json()
    except Exception:  # noqa: BLE001
        return []
    if data.get("error"):
        return []
    result = data.get("result") or {}
    rows = None
    for k, v in result.items():
        if k != "last" and isinstance(v, list):
            rows = v
            break
    if not rows:
        return []
    out: list[Candle] = []
    for row in rows:
        try:
            ts = datetime.fromtimestamp(int(row[0]), tz=timezone.utc)
            out.append(Candle(
                timestamp=ts,
                open=float(row[1]), high=float(row[2]),
                low=float(row[3]), close=float(row[4]),
                volume=float(row[6]),
            ))
        except (KeyError, ValueError, TypeError, IndexError):
            continue
    return out


async def fetch_crypto_ohlc(symbol: str, days: int = 30) -> list[Candle]:
    """Daily OHLC candles for a crypto symbol. Prefers LIVE Kraken public OHLC
    (real exchange prices + volume) for coins Kraken lists; falls back to
    CoinGecko for the rest (crypto Part 3, 2026-06-13)."""
    kr = await fetch_kraken_ohlc(symbol)
    if kr:
        return kr
    coin_id = COIN_MAP.get(symbol.upper())
    if not coin_id:
        return []

    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/ohlc"
    params = {"vs_currency": "usd", "days": str(days)}

    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            r = await client.get(url, params=params)
            if r.status_code != 200:
                return []
            rows = r.json()
    except Exception:  # noqa: BLE001
        return []

    def _parse_cg(raw) -> list[Candle]:
        parsed: list[Candle] = []
        for row in (raw or []):
            if len(row) < 5:
                continue
            ts = datetime.fromtimestamp(int(row[0]) / 1000.0, tz=timezone.utc)
            parsed.append(Candle(
                timestamp=ts,
                open=float(row[1]), high=float(row[2]),
                low=float(row[3]), close=float(row[4]),
                volume=0.0,
            ))
        return parsed

    out = _parse_cg(rows)
    # CoinGecko /ohlc granularity trap (found 2026-07-02): days=90 comes
    # back in 4-DAY candles (~23 bars) -- two short of detect_mode's
    # 25-bar minimum, which silently froze every CoinGecko-fed coin
    # (HBAR/QNT/XDC/IOTA/XYO). Refetch wider when short.
    if len(out) < 25:
        try:
            params["days"] = "180"
            async with httpx.AsyncClient(timeout=12.0) as client:
                r = await client.get(url, params=params)
                if r.status_code == 200:
                    wider = _parse_cg(r.json())
                    if len(wider) > len(out):
                        out = wider
        except Exception:  # noqa: BLE001
            pass
    return out


async def fetch_futures_ohlc(symbol: str, resolution: str = "1d",
                             lookback_days: int = 200) -> list[Candle]:
    """Public Kraken Futures OHLC via the charts API (no auth, no money).
    `symbol` is a Kraken Futures contract, e.g. 'PF_XBTUSD'. Empty on failure.
    Futures Phase 1 (2026-06-13)."""
    import time as _t
    to = int(_t.time())
    frm = to - lookback_days * 86400
    url = f"https://futures.kraken.com/api/charts/v1/trade/{symbol}/{resolution}"
    params = {"from": str(frm), "to": str(to)}
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            r = await client.get(url, params=params)
            if r.status_code != 200:
                return []
            data = r.json()
    except Exception:  # noqa: BLE001
        return []
    raw = data.get("candles") or []
    out: list[Candle] = []
    for c in raw:
        try:
            t = int(c["time"])
            ts = datetime.fromtimestamp(
                t / 1000.0 if t > 1_000_000_000_000 else t, tz=timezone.utc)
            out.append(Candle(
                timestamp=ts,
                open=float(c["open"]), high=float(c["high"]),
                low=float(c["low"]), close=float(c["close"]),
                volume=float(c.get("volume", 0) or 0),
            ))
        except (KeyError, ValueError, TypeError):
            continue
    return out


def _bars_to_candles(bars: list) -> list[Candle]:
    """Convert Alpaca bar dicts ({t,o,h,l,c,v}) to Candle objects."""
    out: list[Candle] = []
    for b in bars:
        try:
            ts = datetime.fromisoformat(str(b["t"]).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            out.append(Candle(
                timestamp=ts,
                open=float(b["o"]), high=float(b["h"]),
                low=float(b["l"]), close=float(b["c"]),
                volume=float(b.get("v", 0) or 0),
            ))
        except (KeyError, ValueError, TypeError):
            continue
    return out


def _yfinance_candles(symbol: str, period: str, interval: str) -> list[Candle]:
    """yfinance fallback (sync — caller runs it in a thread)."""
    try:
        import yfinance as yf
    except ImportError:
        return []
    try:
        df = yf.Ticker(symbol).history(
            period=period, interval=interval, auto_adjust=False)
    except Exception:  # noqa: BLE001
        return []
    if df is None or df.empty:
        return []
    out: list[Candle] = []
    for ts, row in df.iterrows():
        try:
            py_ts = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
            if py_ts.tzinfo is None:
                py_ts = py_ts.replace(tzinfo=timezone.utc)
            out.append(Candle(
                timestamp=py_ts,
                open=float(row["Open"]), high=float(row["High"]),
                low=float(row["Low"]), close=float(row["Close"]),
                volume=float(row.get("Volume", 0) or 0),
            ))
        except (KeyError, ValueError, TypeError):
            continue
    return out


async def fetch_stock_candles(
    symbol: str, period: str = "3mo", interval: str = "1d"
) -> list[Candle]:
    """Stock OHLCV candles.

    Daily bars: Alpaca first (reliable, keys already configured), then
    yfinance as a fallback. Intraday intervals go straight to yfinance.
    """
    if interval == "1d":
        try:
            from app.brokers.alpaca_data import (
                get_daily_bars, market_data_available,
            )
            if market_data_available():
                bars = await get_daily_bars(symbol, _period_to_days(period))
                candles = _bars_to_candles(bars)
                if candles:
                    return candles
        except Exception:  # noqa: BLE001
            pass

    # Fallback to yfinance for any miss or non-daily interval.
    # Fixed 2026-06-11: yf.Ticker().history() is a BLOCKING network
    # call. Calling it inline froze the entire event loop (every agent
    # + the API server) for the duration of each Yahoo request -- and
    # Yahoo rate-limit stalls could freeze the whole bot. to_thread
    # matches the docstring's promise ("caller runs it in a thread").
    import asyncio as _asyncio
    return await _asyncio.to_thread(_yfinance_candles, symbol, period, interval)


async def fetch_candles_for(
    symbol: str, asset_type: str,
) -> list[Candle]:
    """Single dispatch for stock vs crypto."""
    sym = symbol.upper()
    if asset_type == "forex":
        from app.data.forex import fetch_forex_candles
        return await fetch_forex_candles(sym, interval_min=240)
    if asset_type == "crypto" or sym in COIN_MAP:
        return await fetch_crypto_ohlc(sym, days=90)
    return await fetch_stock_candles(sym)
