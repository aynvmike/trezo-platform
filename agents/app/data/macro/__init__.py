"""Macro source registry - picks the active backend from Settings.

Activation order (reads from agents/.env via pydantic-settings):
  1. NASDAQ_DATA_LINK_API_KEY set -> Nasdaq backend.
  2. Any TREZO_MACRO_* value set -> Manual backend.
  3. Otherwise -> Unavailable (regime classifier returns 'neutral').

Future backends slot in at the same `pick_active_source()` decision
point without any change to consumers. See base.py for the interface
and the "why this matters" license commentary.
"""

from __future__ import annotations

from typing import Optional

from app.config import get_settings

from .base import MacroReading, MacroSource, classify_macro_regime
from .manual import ManualMacroSource
from .nasdaq import NasdaqMacroSource
from .twelve_data import TwelveDataMacroSource
from .alpha_vantage import AlphaVantageMacroSource
from .massive import MassiveMacroSource


def pick_active_source() -> Optional[MacroSource]:
    """Return the active source for this process, or None when no
    source is configured. Reads from `Settings` (loaded from
    agents/.env at startup) - not os.environ directly.

    Priority order (first match wins):
      1. Twelve Data  - clean free tier, no redistribution issues
      2. Nasdaq Data Link - legacy backend; their API changed 2026-06
         and existing free keys are getting 403. Keep for accounts
         that still work.
      3. Manual env vars - user types VIX/yield_spread/fed_funds in .env
      4. None - regime classifier returns 'neutral'
    """
    settings = get_settings()
    if (getattr(settings, "massive_api_key", "") or "").strip():
        return MassiveMacroSource()
    if (getattr(settings, "twelve_data_api_key", "") or "").strip():
        return TwelveDataMacroSource()
    if (getattr(settings, "alpha_vantage_api_key", "") or "").strip():
        return AlphaVantageMacroSource()
    if (settings.nasdaq_data_link_api_key or "").strip():
        return NasdaqMacroSource()
    if any(
        (getattr(settings, k, "") or "").strip()
        for k in ("trezo_macro_vix", "trezo_macro_yield_spread", "trezo_macro_fed_funds")
    ):
        return ManualMacroSource()
    return None


async def get_macro_reading() -> MacroReading:
    """Convenience wrapper - returns the active source's reading, or
    an empty reading when no source is configured."""
    src = pick_active_source()
    if src is None:
        return MacroReading(
            source="unavailable",
            note=(
                "No macro source configured. Easiest fix: sign up at "
                "twelvedata.com (free, no card, 800 req/day) and set "
                "TWELVE_DATA_API_KEY in agents/.env. Or set the manual "
                "env vars TREZO_MACRO_VIX / TREZO_MACRO_YIELD_SPREAD / "
                "TREZO_MACRO_FED_FUNDS for instant zero-key fallback."
            ),
        )
    return await src.get_reading()


def active_source_attribution() -> str:
    """The attribution notice for the currently active source. Empty
    string when no source is configured. The UI displays this verbatim
    so each backend's license requirements are honored."""
    src = pick_active_source()
    return src.attribution if src else ""


__all__ = [
    "MacroReading",
    "MacroSource",
    "classify_macro_regime",
    "ManualMacroSource",
    "NasdaqMacroSource",
    "pick_active_source",
    "get_macro_reading",
    "active_source_attribution",
]
