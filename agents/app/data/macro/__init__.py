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


def _configured_sources() -> list[MacroSource]:
    """All configured macro backends in fall-through priority order.
    Working free/public backends first; the Massive/Polygon reader (whose
    free tier can't reach /fed/v1 + the VIX index, so it returned blanks
    while still being 'selected' - the 2026-06-16 'REGIME MASSIVE / blank
    VIX' bug) is demoted; manual is the always-available last resort."""
    s = get_settings()
    out: list[MacroSource] = []
    if (getattr(s, "twelve_data_api_key", "") or "").strip():
        out.append(TwelveDataMacroSource())
    if (getattr(s, "alpha_vantage_api_key", "") or "").strip():
        out.append(AlphaVantageMacroSource())
    if (s.nasdaq_data_link_api_key or "").strip():
        out.append(NasdaqMacroSource())
    if (getattr(s, "massive_api_key", "") or "").strip():
        out.append(MassiveMacroSource())
    if any((getattr(s, k, "") or "").strip()
           for k in ("trezo_macro_vix", "trezo_macro_yield_spread",
                     "trezo_macro_fed_funds")):
        out.append(ManualMacroSource())
    return out


def _score(r: "Optional[MacroReading]") -> int:
    if r is None:
        return -1
    return sum(x is not None for x in
               (r.vix, r.yield_spread_10y3m, r.fed_funds_rate))


async def best_reading_and_source():
    """Walk configured sources; return (reading, source) for the first
    COMPLETE reading, else the most-populated partial, else (None, first
    configured source) so attribution still resolves. ([] -> (None, None))."""
    sources = _configured_sources()
    if not sources:
        return None, None
    best_r, best_src, best_score = None, None, -1
    for src in sources:
        try:
            r = await src.get_reading()
        except Exception:  # noqa: BLE001
            r = None
        if r is not None and r.is_complete():
            return r, src
        sc = _score(r)
        if sc > best_score:
            best_r, best_src, best_score = r, src, sc
    if best_r is not None and best_score > 0:
        return best_r, best_src
    return None, sources[0]


def pick_active_source() -> Optional[MacroSource]:
    """First configured source (fall-through order). Kept for
    backward-compat; get_macro_reading()/best_reading_and_source() do the
    real fall-through across every configured backend."""
    sources = _configured_sources()
    return sources[0] if sources else None


async def get_macro_reading() -> MacroReading:
    """First usable reading across all configured backends (fall-through),
    or a helpful 'unavailable' reading when none return data."""
    reading, _src = await best_reading_and_source()
    if reading is not None and _score(reading) > 0:
        return reading
    if not _configured_sources():
        note = ("No macro source configured. Easiest fix: sign up at "
                "twelvedata.com (free, no card, 800 req/day) and set "
                "TWELVE_DATA_API_KEY in agents/.env, or set the manual "
                "TREZO_MACRO_* env vars.")
    else:
        note = ("Macro backends are configured but none returned data "
                "(keys may be invalid/rate-limited, or the tier lacks the "
                "VIX + treasury endpoints). Try a fresh twelvedata.com key, "
                "or set the manual TREZO_MACRO_* env vars.")
    return MacroReading(source="unavailable", note=note)


def active_source_attribution() -> str:
    """Attribution for the first configured source (UI display)."""
    src = pick_active_source()
    return getattr(src, "attribution", "") if src else ""


__all__ = [
    "MacroReading",
    "MacroSource",
    "classify_macro_regime",
    "ManualMacroSource",
    "NasdaqMacroSource",
    "pick_active_source",
    "best_reading_and_source",
    "get_macro_reading",
    "active_source_attribution",
]
