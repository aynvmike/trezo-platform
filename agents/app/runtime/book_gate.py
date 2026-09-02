"""Per-book admission: may THIS book act on this signal?

Mike, 2026-08-18: "I also do not think the agents are responding to each
book's own setting." He was right, and this is where it went wrong.

Scanners run once for the platform, not once per book. A scanner used to
read `get_bot_settings()` with no argument -- the global row -- to decide
whether its strategy is on and what TCS floor to use, and Risk Manager
then scored the signal against `get_bot_settings(payload.user_id)`, which
for a scanner signal (no user_id) was the global row too. Only then did
Trade Execution fan the approved signal out across every book in
paper_accounts. (BI-03, 2026-09-01: scanners and the risk gate now judge
an unscoped signal at the LOWEST enabled book's floor -- as permissive as
the most permissive book -- precisely so that the per-book floor applied
HERE is the one that binds.)

The result: one book's toggles decided for all of them. Turning crypto
off on the 25k book did nothing, because the primary's crypto_enabled
was what the scanner read. Raising the 75k's TCS floor did nothing, for
the same reason. Three books, one opinion.

Fixing it at the scanner would mean running every scanner once per book
-- N times the API calls to answer a question about the tape, which is
identical for everyone. The tape is global; the APPETITE is per book. So
scanners stay global and the appetite check moves to the fan-out, which
is the first place a book actually has a name.

Adding a strategy? Add its gate below. A strategy with no entry is
admitted everywhere, which is the right default (a new strategy is not
secretly disabled) but a silent one -- hence `ungated()`, which the
guard test uses to keep the list honest.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass(frozen=True)
class Gate:
    """One toggle in Bot Tuning, and what it governs."""

    name: str
    flag: str                                   # BotSettings attribute
    applies: Callable[[str, str], bool]         # (asset_type, strategy)
    why: str = ""


def _is(asset: str) -> Callable[[str, str], bool]:
    return lambda at, _s: at == asset


def _named(*words: str) -> Callable[[str, str], bool]:
    return lambda _at, s: any(w in s for w in words)


GATES: tuple[Gate, ...] = (
    Gate("crypto", "crypto_enabled", _is("crypto"),
         "coin exposure is the toggle most likely to differ per book"),
    Gate("forex", "crypto_enabled", _is("forex"),
         "forex has no toggle of its own yet; it rides the 24/7 switch"),
    Gate("extended", "extended_enabled", _named("extended"),
         "extended-hours entries"),
    Gate("stms", "stms_enabled", _named("stms", "orb"),
         "opening-range / short-term momentum"),
    Gate("pattern", "pattern_enabled", _named("pattern"),
         "chart-pattern entries"),
)


def ungated(asset_type: str, strategy: str) -> bool:
    """True when nothing in GATES governs this signal. Not an error --
    just the fact the guard test asserts about, so a strategy is never
    left ungated by accident rather than on purpose."""
    at = (asset_type or "").lower()
    st = (strategy or "").lower()
    return not any(g.applies(at, st) for g in GATES)


def min_tcs_for(settings, strategy: str, *, tcs_bump: int = 0) -> int:
    """This book's TCS floor for this strategy, plus any per-book bump.

    Mirrors the crypto carve-out Risk Manager and the crypto scanner
    both apply (Mike 2026-07-23: crypto runs under the stock floor
    because per-coin stops are tighter). Duplicating the rule is worse
    than sharing it, but the alternative here is importing Risk Manager
    into the execution path, and a floor that disagrees with the one
    that approved the signal would reject everything crypto.

    `tcs_bump` (KS-5, TE-19): extra conviction THIS book demands on top
    of its floor -- weekly recovery (+RECOVERY_TCS_BUMP) and margin
    territory (+TREZO_MARGIN_TCS_BUMP), each decided per book at the
    fan-out. Risk Manager adds the same bumps to its ONE global floor;
    before this the per-book verdict ignored them, so a recovering book
    was admitted at its ordinary bar."""
    floor = int(getattr(settings, "tcs_threshold", 70) or 70)
    if str(strategy or "").lower().startswith("crypto"):
        try:
            from app.config import get_settings
            floor = min(floor, int(getattr(
                get_settings(), "trezo_crypto_tcs_floor", 35)))
        except Exception:  # noqa: BLE001
            pass
    if os.getenv("TREZO_COVERAGE_MODE", "0") != "0":
        try:
            floor = min(floor, int(float(
                os.getenv("TREZO_COVERAGE_TCS", "40"))))
        except (TypeError, ValueError):
            floor = min(floor, 40)
    # KS-5 / TE-19: the bump rides on top of every carve-out above.
    try:
        floor += max(0, int(tcs_bump or 0))
    except (TypeError, ValueError):
        pass
    return floor


@dataclass(frozen=True)
class Verdict:
    """Why a book did or did not take a signal.

    `event` matters as much as `ok`: the post-mortem loop learns from
    "would_have_traded" rows, so a book sitting out because Auto-trade
    is off has to keep producing them. Losing that distinction would
    silently stop the learning loop on every observe-only book -- the
    kind of regression that shows up as "the bot got worse" months
    later with nothing in the logs."""

    ok: bool
    reason: str = ""
    event: str = ""

    def __bool__(self) -> bool:      # so `if admits(...)` reads right
        return self.ok


def admits(settings, *, asset_type: str, strategy: str,
           tcs: Optional[float] = None, tcs_bump: int = 0) -> Verdict:
    """May this book take this signal?

    Takes the already-loaded settings object rather than a user_id, so
    it is pure and testable and cannot be handed the wrong book by
    accident -- the caller has already bound one. `tcs_bump` is this
    book's own extra conviction (recovery / margin territory, KS-5 and
    TE-19) and is added to its floor before the TCS check.

    Fails OPEN on anything unexpected. A settings blip must not silently
    freeze a book; the historical behaviour was to trade, and a gate
    that turns a transient error into a halt is worse than the leak it
    was written to close.
    """
    try:
        at = (asset_type or "").lower()
        st = (strategy or "").lower()

        if not getattr(settings, "auto_trade_enabled", True):
            return Verdict(False, "auto-trade is OFF for this book",
                           "would_have_traded")

        for g in GATES:
            if g.applies(at, st) and not getattr(settings, g.flag, True):
                return Verdict(
                    False, f"{g.name} is OFF for this book ({g.flag})",
                    "book_declined")

        if tcs is not None:
            try:
                _bump = max(0, int(tcs_bump or 0))
            except (TypeError, ValueError):
                _bump = 0
            floor = min_tcs_for(settings, st, tcs_bump=_bump)
            if float(tcs) < floor:
                _bump_note = f" (incl. +{_bump} bump)" if _bump else ""
                return Verdict(
                    False,
                    f"TCS {float(tcs):g} is under this book's floor of "
                    f"{floor}{_bump_note}",
                    "book_declined")
        return Verdict(True)
    except Exception:  # noqa: BLE001
        return Verdict(True)
