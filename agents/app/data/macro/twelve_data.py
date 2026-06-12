"""Twelve Data macro backend.

Sign up: https://twelvedata.com  -> free 800 requests/day, no credit card,
commercial use allowed. The free key returns:
  - VIX index quote (?symbol=VIX)
  - US 10-year treasury yield (?symbol=US10Y)
  - US 3-month T-bill yield (?symbol=US3M)
  - (Fed funds rate: approximated from US3M which historically tracks
    Fed Funds within 0.10%. For exact Fed Funds we'd need a different
    source; the 3M proxy is good enough for regime classification.)

Activation:
  1. Sign up at twelvedata.com (instant, no card)
  2. Add to agents/.env:
       TWELVE_DATA_API_KEY=<your_key>
  3. Restart agents - the registry picks this backend automatically.

Licensing: Twelve Data's free tier permits use in commercial apps + bots
with their attribution (which we include in the `attribution` field).
No redistribution restriction like FRED.
"""

from __future__ import annotations

import asyncio
from typing import Optional

import httpx

from app.config import get_settings
from .base import MacroReading, MacroSource


_BASE = "https://api.twelvedata.com"


class TwelveDataMacroSource:
    """Reads VIX + treasury yields from Twelve Data's quote endpoint."""

    name = "twelve_data"
    attribution = "Macro data via Twelve Data (twelvedata.com)"

    def __init__(self, api_key: Optional[str] = None):
        s = get_settings()
        self._key = api_key or (getattr(s, "twelve_data_api_key", "") or "").strip()

    async def _quote(self, symbol: str) -> Optional[float]:
        """Fetch a single quote.price. Returns None on any failure -
        the consumer treats partial readings gracefully."""
        if not self._key:
            return None
        url = f"{_BASE}/quote"
        params = {"symbol": symbol, "apikey": self._key}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(url, params=params)
                if r.status_code != 200:
                    return None
                data = r.json()
                # Twelve Data returns {"price": "15.42", ...} or
                # {"code": 429, "message": "..."} on error
                if "price" in data:
                    return float(data["price"])
                if "close" in data:
                    return float(data["close"])
                return None
        except Exception:  # noqa: BLE001
            return None

    async def get_reading(self) -> MacroReading:
        # Fetch all three concurrently to use the free quota efficiently
        vix, y10, y3m = await asyncio.gather(
            self._quote("VIX"),
            self._quote("US10Y"),
            self._quote("US3M"),
        )

        spread = None
        if y10 is not None and y3m is not None:
            spread = round(y10 - y3m, 3)

        # Approximate Fed Funds with the 3-month T-bill yield; tracks
        # within ~0.10% historically. Good enough for regime calls.
        fed_funds = y3m

        return MacroReading(
            vix=vix,
            yield_spread_10y3m=spread,
            fed_funds_rate=fed_funds,
            source=self.name,
            note=(
                "Treasury yield spread = US10Y - US3M (Twelve Data quotes). "
                "Fed Funds approximated via US3M T-bill yield (typically "
                "within 0.10% of effective Fed Funds rate)."
            ),
        )
