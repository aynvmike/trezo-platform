"""Nasdaq Data Link macro source - test backend.

License story per series:
  USTREASURY/YIELD     - US Treasury Department source data, public
                         domain underlying. Nasdaq Data Link mirrors
                         it; redistribution of public-domain data is
                         allowed. SAFE for Trezo's multi-user future.
  FRED/DFF (Fed Funds) - This is FRED data REBADGED on Nasdaq. Same
                         FRED ToU applies. NOT SAFE for redistribution.
                         We do NOT pull this from Nasdaq.
  VIX                  - Nasdaq Data Link discontinued free VIX in
                         2022. Not available here. Use Alpaca's VIXY
                         price proxy (a separate backend) or CBOE's
                         direct public CSV.

So this backend reliably provides ONLY the yield curve. VIX and Fed
Funds come back as None. The classifier degrades to 'neutral' until
more sources are wired - that's the intended behavior.

API key (free signup at data.nasdaq.com) is required - rate limit
is 50 calls/day anonymous, 300+/day with a key. With our 24h cache
we use ~1 call/day.
"""

from __future__ import annotations

import time
from typing import Optional

import httpx
import structlog

from app.config import get_settings
from .base import MacroReading

log = structlog.get_logger("trezo.data.macro.nasdaq")

_BASE = "https://data.nasdaq.com/api/v3/datasets"
_CACHE_TTL = 24 * 60 * 60  # 24 hours - macro moves slowly


class NasdaqMacroSource:
    """Test backend - pulls US Treasury yield curve from Nasdaq Data
    Link. Set NASDAQ_DATA_LINK_API_KEY in agents/.env to enable."""

    name = "nasdaq"

    # The "USTREASURY/YIELD" dataset on Nasdaq Data Link mirrors US
    # Treasury Department data, which is public domain. Trezo can
    # redistribute derived readings (regime classifications) freely.
    # We DO display attribution as a courtesy.
    attribution = (
        "Yield-curve data via Nasdaq Data Link (USTREASURY/YIELD). "
        "Underlying source: US Treasury Department - public domain."
    )

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, float, str]] = {}

    def _api_key(self) -> Optional[str]:
        settings = get_settings()
        key = (settings.nasdaq_data_link_api_key or "").strip()
        return key or None

    async def _fetch_yield_spread(self) -> Optional[tuple[float, str]]:
        """Pull the most recent (10y - 3m) Treasury yield spread.

        Returns (spread_percentage_points, observation_date_iso) or
        None when the API key is missing or the call fails."""
        key = self._api_key()
        if not key:
            return None

        # 24h cache.
        now = time.time()
        hit = self._cache.get("yield_spread")
        if hit is not None and (now - hit[1]) < _CACHE_TTL:
            return (hit[0], hit[2])

        # USTREASURY/YIELD returns daily rows: [date, 1mo, 2mo, 3mo,
        # 6mo, 1yr, 2yr, 3yr, 5yr, 7yr, 10yr, 20yr, 30yr]. We want
        # 10yr - 3mo from the most recent row.
        url = f"{_BASE}/USTREASURY/YIELD.json"
        params = {"api_key": key, "rows": 5}  # 5 rows in case latest is null

        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.get(url, params=params)
            if r.status_code != 200:
                log.warning("nasdaq.fetch.http_error", status=r.status_code)
                return None
            data = r.json()
        except Exception as e:  # noqa: BLE001
            log.warning("nasdaq.fetch.error", error=str(e))
            return None

        dataset = data.get("dataset") or {}
        col_names = dataset.get("column_names") or []
        rows = dataset.get("data") or []
        if not rows or not col_names:
            return None

        # Find the column indices for 3 MO and 10 YR.
        try:
            i_3mo = next(
                i for i, c in enumerate(col_names)
                if "3" in c and ("MO" in c.upper() or "MONTH" in c.upper())
            )
            i_10yr = next(
                i for i, c in enumerate(col_names)
                if "10" in c and ("YR" in c.upper() or "YEAR" in c.upper())
            )
        except StopIteration:
            log.warning("nasdaq.parse.cols_missing", cols=col_names)
            return None

        # Walk newest-first for the first row with both values present.
        for row in rows:
            try:
                v3 = row[i_3mo]
                v10 = row[i_10yr]
                date = str(row[0])
            except (IndexError, TypeError):
                continue
            if v3 is None or v10 is None:
                continue
            try:
                spread = float(v10) - float(v3)
            except (TypeError, ValueError):
                continue
            self._cache["yield_spread"] = (spread, now, date)
            return (spread, date)

        return None

    async def get_reading(self) -> MacroReading:
        spread_pair = await self._fetch_yield_spread()
        if spread_pair is None:
            return MacroReading(
                source="unavailable",
                note=(
                    "Nasdaq Data Link not configured or unreachable. "
                    "Set NASDAQ_DATA_LINK_API_KEY in agents/.env."
                ),
            )

        spread, obs_date = spread_pair
        return MacroReading(
            vix=None,                     # Nasdaq free tier dropped VIX in 2022.
            yield_spread_10y3m=spread,
            fed_funds_rate=None,          # FRED/DFF carries FRED's ToU; we skip.
            source="nasdaq",
            observation_dates={"USTREASURY/YIELD": obs_date},
            note=(
                f"Yield curve as of {obs_date}: 10y - 3m = "
                f"{spread:+.2f} percentage points. VIX and Fed Funds "
                f"are not pulled from Nasdaq (license / availability) - "
                f"plug in a second backend to fill them."
            ),
        )
