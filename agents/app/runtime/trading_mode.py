"""Trading mode — the paper / live master switch (Phase 10a).

Trezo trades on paper by default. Live (real-money) execution is gated
behind TWO independent conditions, BOTH of which must hold:

  1. TRADING_MODE=live is set in the environment, and
  2. a live executor has been wired in and _LIVE_EXECUTOR_AVAILABLE
     flipped to True (Phase 10b or later).

Until the live executor exists, live_trading_enabled() always returns
False — setting the environment variable alone changes nothing real.
Every execution path must check live_trading_enabled(), never the raw
mode string, so this stays the single chokepoint for real money.
"""

from __future__ import annotations

from app.config import get_settings

# Flipped to True only when the live executor is built AND reviewed.
# This is the hard gate. Phase 10a ships with it False on purpose.
_LIVE_EXECUTOR_AVAILABLE = False

VALID_MODES = ("paper", "live")


def get_trading_mode() -> str:
    """The configured mode, always one of VALID_MODES.

    Anything unrecognised falls back to the safe default, 'paper'.
    """
    raw = (get_settings().trading_mode or "paper").strip().lower()
    return raw if raw in VALID_MODES else "paper"


def live_requested() -> bool:
    """True when the environment asks for live mode."""
    return get_trading_mode() == "live"


def live_trading_enabled() -> bool:
    """True only when live is requested AND the live executor exists.

    This is the gate every execution path must consult before placing a
    real-money order. In Phase 10a it is always False.
    """
    return live_requested() and _LIVE_EXECUTOR_AVAILABLE


def mode_banner() -> str:
    """A plain-language description of the current mode, for logs / UI."""
    if live_trading_enabled():
        return "LIVE - real-money orders are active."
    if live_requested():
        return ("LIVE is requested, but the live executor is not wired "
                "yet (Phase 10b). All trades remain on paper.")
    return "PAPER - all trades are simulated. No real money is at risk."
