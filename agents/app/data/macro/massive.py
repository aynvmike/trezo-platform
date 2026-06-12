"""Massive (massive.com / polygon.io) macro backend.

Massive is Polygon.io rebranded. They expose treasury yields, Fed Funds,
inflation, GDP via /fed/v1/* endpoints. VIX via index aggregates.

API docs: https://polygon.io/docs/rest

Auth: query parameter ?apiKey=<key>. Bearer token also accepted.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Optional

import httpx

from app.config import get_settings
from .base import MacroReading, MacroSource


_BASE = "https://api.polygon.io"


class MassiveMacroSource:
    """Polygon-via-Massive macro reader.

    Endpoints used:
      GET /fed/v1/treasury-yields     - yield curve snapshot
      GET /fed/v1/federal-funds-rate  - effective Fed Funds rate
      GET /v2/aggs/ticker/I:VIX/prev  - VIX prior-close (index ticker)
    """

    name = "massive"
    attribution = "Macro data via Massive (massive.com / Polygon.io)"

    def __init__(self, api_key: Optional[str] = None):
        s = get_settings()
        self._key = api_key or (getattr(s, "massive_api_key", "") or "").strip()

    async def _get_json(self, path: str, params: Optional[dict] = None) -> Optional[dict]:
        if not self._key:
            return None
        p = {"apiKey": self._key, **(params or {})}
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(_BASE + path, params=p)
                if r.status_code != 200:
                    return None
                return r.json()
        except Exception:  # noqa: BLE001
            return None

    async def _treasury_yields(self) -> tuple[Optional[float], Optional[float]]:
        """Returns (10y, 3m) yields. Polygon's /fed/v1/treasury-yields
        returns the full curve in one call - cheap."""
        data = await self._get_json("/fed/v1/treasury-yields", {"limit": 1})
        if not data or "results" not in data:
            return None, None
        rows = data["results"]
        if not rows:
            return None, None
        latest = rows[0]
        # Field names follow Polygon convention: "yield_10_year", "yield_3_month"
        y10 = latest.get("yield_10_year") or latest.get("10y")
        y3m = latest.get("yield_3_month") or latest.get("3m")
        try:
            return (float(y10) if y10 is not None else None,
                    float(y3m) if y3m is not None else None)
        except (TypeError, ValueError):
            return None, None

    async def _fed_funds(self) -> Optional[float]:
        data = await self._get_json("/fed/v1/federal-funds-rate", {"limit": 1})
        if not data or "results" not in data:
            return None
        rows = data["results"]
        if not rows:
            return None
        v = rows[0].get("rate") or rows[0].get("value")
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    async def _vix(self) -> Optional[float]:
        # Polygon exposes VIX as index ticker I:VIX
        data = await self._get_json("/v2/aggs/ticker/I:VIX/prev", {"adjusted": "true"})
        if not data or "results" not in data:
            return None
        rows = data["results"]
        if not rows:
            return None
        v = rows[0].get("c")  # close
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    async def get_reading(self) -> MacroReading:
        (y10, y3m), fed_funds, vix = await asyncio.gather(
            self._treasury_yields(),
            self._fed_funds(),
            self._vix(),
        )
        spread = None
        if y10 is not None and y3m is not None:
            spread = round(y10 - y3m, 3)
        return MacroReading(
            vix=vix,
            yield_spread_10y3m=spread,
            fed_funds_rate=fed_funds,
            source=self.name,
            note=(
                "Yields: GET /fed/v1/treasury-yields (10y - 3m). "
                "Fed Funds: GET /fed/v1/federal-funds-rate. "
                "VIX: GET /v2/aggs/ticker/I:VIX/prev. "
                "If 404 on any of these, Polygon may have changed paths -"
                " check polygon.io/docs/rest and update."
            ),
        )
