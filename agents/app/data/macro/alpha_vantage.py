"""Alpha Vantage macro backend.

Free tier: 25 requests/day, 5/min - tight but enough for our use.
Sign up: https://www.alphavantage.co/support/#api-key

Macro endpoints:
  - TREASURY_YIELD (10year, 3month) -> yield spread
  - FEDERAL_FUNDS_RATE -> fed_funds_rate
  - VIX: not directly available; use the daily quote of the VIX
    index symbol via the GLOBAL_QUOTE function instead.

Licensing: free tier permits commercial app use with attribution.
No FRED-style redistribution restriction.
"""

from __future__ import annotations

import asyncio
from typing import Optional

import httpx

from app.config import get_settings
from .base import MacroReading, MacroSource


_BASE = "https://www.alphavantage.co/query"


class AlphaVantageMacroSource:
    name = "alpha_vantage"
    attribution = "Macro data via Alpha Vantage (alphavantage.co)"

    def __init__(self, api_key: Optional[str] = None):
        s = get_settings()
        self._key = api_key or (getattr(s, "alpha_vantage_api_key", "") or "").strip()

    async def _call(self, params: dict) -> Optional[dict]:
        if not self._key:
            return None
        params = {**params, "apikey": self._key}
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(_BASE, params=params)
                if r.status_code != 200:
                    return None
                return r.json()
        except Exception:  # noqa: BLE001
            return None

    async def _treasury_yield(self, maturity: str) -> Optional[float]:
        """Returns most recent yield % for the given maturity."""
        data = await self._call({
            "function": "TREASURY_YIELD",
            "interval": "daily",
            "maturity": maturity,
        })
        if not data or "data" not in data:
            return None
        rows = data["data"]
        if not rows:
            return None
        # Most recent row first; find first non-null
        for row in rows[:10]:
            v = row.get("value")
            if v not in (None, "", "."):
                try:
                    return float(v)
                except (TypeError, ValueError):
                    continue
        return None

    async def _fed_funds(self) -> Optional[float]:
        data = await self._call({
            "function": "FEDERAL_FUNDS_RATE",
            "interval": "daily",
        })
        if not data or "data" not in data:
            return None
        for row in data["data"][:10]:
            v = row.get("value")
            if v not in (None, "", "."):
                try:
                    return float(v)
                except (TypeError, ValueError):
                    continue
        return None

    async def _vix(self) -> Optional[float]:
        """VIX index quote. Alpha Vantage exposes VIX under VIX symbol."""
        data = await self._call({
            "function": "GLOBAL_QUOTE",
            "symbol": "VIX",
        })
        if not data:
            return None
        q = data.get("Global Quote") or data.get("global_quote") or {}
        price = q.get("05. price") or q.get("price")
        if price in (None, ""):
            return None
        try:
            return float(price)
        except (TypeError, ValueError):
            return None

    async def get_reading(self) -> MacroReading:
        # Sequential fetches with 1.2s pacing (Task #82, 2026-06-05).
        # Free tier rate-limits at 1 req/sec; concurrent gather() hits
        # the limit on the 3rd parallel call. 1.2s spacing keeps us
        # safely under 1 req/sec across the 4 calls (~5s total).
        # Macro only refreshes every 6h so the extra 4s is invisible.
        y10 = await self._treasury_yield("10year")
        await asyncio.sleep(1.2)
        y3m = await self._treasury_yield("3month")
        await asyncio.sleep(1.2)
        ff  = await self._fed_funds()
        await asyncio.sleep(1.2)
        vix = await self._vix()
        spread = None
        if y10 is not None and y3m is not None:
            spread = round(y10 - y3m, 3)
        return MacroReading(
            vix=vix,
            yield_spread_10y3m=spread,
            fed_funds_rate=ff,
            source=self.name,
            note=(
                "Yields: TREASURY_YIELD (10year - 3month). "
                "Fed Funds: FEDERAL_FUNDS_RATE. "
                "VIX: GLOBAL_QUOTE on VIX index. "
                "Free tier 25 req/day - bot uses 4-12/day."
            ),
        )
