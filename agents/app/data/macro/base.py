"""Macro data source - common interface.

Trezo agents (Adaptive Scope, Market Horizon) read three macro inputs:
  - VIX level (fear)
  - 10y-3m Treasury yield spread (curve / recession proxy)
  - Effective Fed Funds rate (policy stance)

Multiple backends can provide these. The agents only ever talk to the
`MacroSource` interface here, so backends swap without touching agent
code. That insulates us from licensing surprises - if a backend turns
out to forbid redistribution (which matters once Trezo serves users
beyond Mike), we drop it and plug in another.

Why this matters: the FRED integration was reverted on 2026-05-29
because FRED's ToU restricts redistribution. The adapter pattern
documents the licensing story per backend so future-Nova doesn't
re-pull a license-incompatible source by accident.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable


@dataclass
class MacroReading:
    """Three macro inputs. Any field may be None when the active
    backend can't supply it (e.g. Nasdaq Data Link's free tier doesn't
    have VIX). Consumer logic must handle the partial case."""

    vix: Optional[float] = None
    yield_spread_10y3m: Optional[float] = None  # percentage points
    fed_funds_rate: Optional[float] = None      # percent
    # Source name (e.g. "nasdaq", "manual", "alpaca-proxy") so the UI
    # can display the right attribution notice.
    source: str = "unavailable"
    # Per-series observation dates ({"VIX": "2026-05-28", ...}).
    observation_dates: Optional[dict] = None
    # Free-text note - e.g. "Yield curve from US Treasury Direct via
    # Nasdaq Data Link mirror (public domain)."
    note: Optional[str] = None

    def is_complete(self) -> bool:
        return (
            self.vix is not None
            and self.yield_spread_10y3m is not None
            and self.fed_funds_rate is not None
        )


@runtime_checkable
class MacroSource(Protocol):
    """All macro backends implement this. Async because most backends
    hit a network API; the manual backend is synchronous internally
    but still exposes async for a uniform call site."""

    name: str  # "nasdaq" | "alpaca-proxy" | "manual" | "treasury-direct"

    # The attribution notice each backend's terms require. Empty string
    # when the backend's data is fully public domain.
    attribution: str

    async def get_reading(self) -> MacroReading:
        ...


def classify_macro_regime(reading: MacroReading) -> tuple[str, str]:
    """Translate a MacroReading into a regime label + plain-English
    explanation. Returns ('neutral', 'reason') when the reading is
    incomplete - the agents fall back to stock-price-only regime reads
    in that case.

    Modes:
      "risk_off"  - VIX > 25 AND yield curve inverted (T10Y3M < 0).
                    Fear + recession warning. Tighten everything.
      "growth"    - VIX < 16 AND curve steeper than +1.0%. Complacent
                    market + steep curve = risk-on regime.
      "neutral"   - everything else, or backend unavailable.
    """
    if not reading.is_complete():
        return (
            "neutral",
            "Macro reading incomplete - falling back to stock-price-only regime read.",
        )

    vix = float(reading.vix)
    spread = float(reading.yield_spread_10y3m)

    if vix > 25 and spread < 0:
        return (
            "risk_off",
            f"VIX {vix:.1f} > 25 AND yield curve inverted ({spread:.2f}%) - "
            f"fear + recession warning. Adaptive Scope tightens.",
        )
    if vix < 16 and spread > 1.0:
        return (
            "growth",
            f"VIX {vix:.1f} < 16 AND yield curve steep ({spread:.2f}%) - "
            f"complacent market + healthy curve. Adaptive Scope opens up.",
        )
    return (
        "neutral",
        f"VIX {vix:.1f}, curve {spread:+.2f}%, Fed Funds {reading.fed_funds_rate:.2f}% - "
        f"in-between regime; no macro tilt applied.",
    )
