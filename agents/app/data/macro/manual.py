"""Manual macro source - values from Settings (read from agents/.env).

No API calls, no license risk. Mike enters the current macro values
in agents/.env. Works as a fallback for any backend that fails or
as the primary when Mike just wants to test the regime classifier
without hooking up a feed.

Env vars (all optional, read by pydantic-settings into Settings):
  TREZO_MACRO_VIX            -> e.g. "16.2"
  TREZO_MACRO_YIELD_SPREAD   -> e.g. "0.18" (percentage points)
  TREZO_MACRO_FED_FUNDS      -> e.g. "5.33" (percent)

License: zero. Mike's own typed input.
"""

from __future__ import annotations

from typing import Optional

from app.config import get_settings

from .base import MacroReading


class ManualMacroSource:
    name = "manual"
    attribution = ""  # No third-party data, no notice needed.

    @staticmethod
    def _parse(raw: str) -> Optional[float]:
        s = (raw or "").strip()
        if not s:
            return None
        try:
            return float(s)
        except (TypeError, ValueError):
            return None

    async def get_reading(self) -> MacroReading:
        settings = get_settings()
        vix = self._parse(settings.trezo_macro_vix)
        spread = self._parse(settings.trezo_macro_yield_spread)
        fed = self._parse(settings.trezo_macro_fed_funds)
        any_set = vix is not None or spread is not None or fed is not None
        return MacroReading(
            vix=vix,
            yield_spread_10y3m=spread,
            fed_funds_rate=fed,
            source="manual" if any_set else "unavailable",
            observation_dates=None,
            note=(
                "Values from TREZO_MACRO_* in agents/.env. Update them "
                "when the macro picture changes."
                if any_set else
                "No TREZO_MACRO_* values set; manual backend has nothing to report."
            ),
        )
