"""Forex data feed -- Kraken public OHLC for the major pairs (2026-07-02).

FOUNDATION ONLY for the Forex layer: free, key-less candle data via
Kraken's public API (the same venue the crypto side already trusts), so
the forex scanner Part 2 can be wired without a new vendor. Alpha
Vantage FX was considered and rejected for polling (25 req/day free cap).

Not imported by any agent yet -- wiring the scanner + a forex pocket is
the next part. Long-only fiat pairs make no sense (every FX position is
long one currency short the other), so the eventual engine models BOTH
directions -- another reason it gets its own careful part.
"""

from __future__ import annotations

from typing import Optional

# Kraken accepts these query names for the fiat majors.
FOREX_MAJORS: dict[str, str] = {
    "EURUSD": "EURUSD",
    "GBPUSD": "GBPUSD",
    "USDJPY": "USDJPY",
    "AUDUSD": "AUDUSD",
    "USDCAD": "USDCAD",
    # 2026-07-13 (Mike): five liquid crosses so the forex desk trains on
    # more than the majors. All carried on Kraken public OHLC.
    "USDCHF": "USDCHF",
    "EURGBP": "EURGBP",
    "EURJPY": "EURJPY",
    "EURCAD": "EURCAD",
    "EURAUD": "EURAUD",
}

_KRAKEN_OHLC_URL = "https://api.kraken.com/0/public/OHLC"


async def fetch_forex_candles(pair: str, interval_min: int = 60,
                              limit: int = 200) -> list:
    """OHLC candles for a major pair, oldest->newest, as app Candle
    objects. Empty list on any failure -- callers must stay fail-open."""
    name = FOREX_MAJORS.get((pair or "").upper().replace("/", ""))
    if not name:
        return []
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(_KRAKEN_OHLC_URL,
                                    params={"pair": name,
                                            "interval": str(int(interval_min))})
            resp.raise_for_status()
            data = resp.json()
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(data, dict) or data.get("error"):
        return []
    result = data.get("result") or {}
    rows = None
    for k, v in result.items():
        if k != "last" and isinstance(v, list):
            rows = v
            break
    if not rows:
        return []
    try:
        from app.patterns import Candle
    except Exception:  # noqa: BLE001
        return []
    from datetime import datetime, timezone
    out = []
    for r in rows[-int(limit):]:
        try:
            out.append(Candle(
                timestamp=datetime.fromtimestamp(float(r[0]), tz=timezone.utc),
                open=float(r[1]), high=float(r[2]),
                low=float(r[3]), close=float(r[4]),
                volume=float(r[6]),
            ))
        except Exception:  # noqa: BLE001
            continue
    return out
