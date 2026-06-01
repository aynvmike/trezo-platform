"""Adaptive Scope — the decision logic that turns market-regime reads and
detected events into concrete scope adjustments.

Phase 7.5. This module is pure logic: given a RegimeRead or an event
payload it returns ScopeAdjustment records. It holds no state and does no
I/O — the AdaptiveScopeAgent owns timing, persistence and autonomy mode;
runtime/scope.py owns the live state the Risk Manager reads.

Guardrails are hard caps. The engine may only ever make risk-*reducing*
moves — tighten stops, raise the confidence bar, pause or flag — never
loosen them. Even in 'full' autonomy it cannot push past these limits.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

from app.strategies import library


# --- Guardrails (hard caps) ------------------------------------------
MIN_STOP_MULTIPLIER = 0.5     # stops may be tightened at most 50%
MAX_STOP_MULTIPLIER = 1.0     # never loosened beyond the strategy baseline
MAX_TCS_BUMP = 150            # the confidence bar may be raised at most +150
MAX_FLAGGED_TICKERS = 20
FLAG_TTL_MINUTES = 24 * 60    # a flagged ticker clears after 24h by default
POSTURE_TTL_MINUTES = 6 * 60  # a regime posture is re-evaluated within 6h

# Which Trezo strategy a signal can carry, mapped to its library family.
TREZO_STRATEGY_FAMILY: dict[str, str] = {
    "stms": "momentum",
    "crypto": "momentum",
    "crypto_scalp": "mean_reversion",
    "crypto_swing": "trend",
    "crypto_dca": "mean_reversion",
    "wheel_csp": "income",
    "wheel_cc": "income",
    "options": "income",
    "pattern": "trend",
    "default": "trend",
}

# Per-regime posture: (stop multiplier, TCS bump). Tighter + higher in
# rougher regimes; baseline in calm uptrends.
_REGIME_POSTURE: dict[str, tuple[float, int]] = {
    "trending_up":     (1.00,   0),
    "low_volatility":  (1.00,   0),
    "choppy":          (0.85,  25),
    "trending_down":   (0.75,  50),
    "high_volatility": (0.70,  75),
    "risk_off":        (0.60, 150),
}

# Event types worth flagging a ticker over.
_FLAGGABLE_EVENTS = {
    "legal", "guidance", "leadership", "m_and_a",
    "earnings", "earnings_upcoming",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


@dataclass
class ScopeAdjustment:
    """One change to Trezo's trading scope, proposed or applied."""

    id: str
    created_at: str
    action: str            # 'set_posture' | 'flag_ticker'
    scope: str             # 'market' | a ticker symbol
    reason: str
    trigger: str           # 'regime:<r>' | 'event:<type>'
    severity: str          # low | medium | high
    ttl_minutes: int
    status: str = "applied"          # suggested | applied | expired | dismissed
    # posture-only fields (neutral defaults for flag_ticker)
    stop_multiplier: float = 1.0
    tcs_bump: int = 0
    paused_strategies: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return asdict(self)


def regime_posture(read) -> ScopeAdjustment:
    """Translate a RegimeRead into the market-wide posture adjustment."""
    regime = getattr(read, "regime", "choppy")
    stop_mult, tcs_bump = _REGIME_POSTURE.get(regime, (0.85, 25))
    stop_mult = _clamp(stop_mult, MIN_STOP_MULTIPLIER, MAX_STOP_MULTIPLIER)
    tcs_bump = int(_clamp(tcs_bump, 0, MAX_TCS_BUMP))

    play = library.playbook_for(regime)
    paused_families = set(play.pause) if play else set()
    paused = tuple(sorted(
        s for s, fam in TREZO_STRATEGY_FAMILY.items()
        if fam in paused_families
    ))

    if regime in ("risk_off", "high_volatility"):
        severity = "high"
    elif regime in ("trending_down", "choppy"):
        severity = "medium"
    else:
        severity = "low"

    return ScopeAdjustment(
        id=new_id(),
        created_at=_now(),
        action="set_posture",
        scope="market",
        reason=getattr(read, "summary", f"Market regime: {regime}."),
        trigger=f"regime:{regime}",
        severity=severity,
        ttl_minutes=POSTURE_TTL_MINUTES,
        stop_multiplier=stop_mult,
        tcs_bump=tcs_bump,
        paused_strategies=paused,
    )


def event_adjustment(payload: dict, mode: str = "guarded") -> ScopeAdjustment | None:
    """Decide whether a detected event warrants flagging its ticker.

    Returns a flag_ticker adjustment, or None if the event is not
    actionable at the current autonomy mode.
    """
    ticker = str(payload.get("ticker") or "").upper()
    if not ticker:
        return None
    event_type = str(payload.get("event_type") or "general")
    severity = str(payload.get("severity") or "low")
    sentiment = str(payload.get("sentiment") or "neutral")

    # Guarded mode acts on medium/high severity only; full mode also acts
    # on low severity. (Suggest mode is handled by the agent: it records
    # the proposal but applies nothing.)
    if mode == "guarded" and severity == "low":
        return None

    # A clearly positive headline is not a reason to flag a ticker —
    # except an upcoming earnings date, which is binary risk either way.
    if sentiment == "positive" and event_type not in (
        "earnings", "earnings_upcoming"
    ):
        return None

    if event_type not in _FLAGGABLE_EVENTS:
        return None

    headline = str(payload.get("headline") or event_type)
    reason = (f"{ticker}: {event_type.replace('_', ' ')} event "
              f"({severity} severity) — {headline}")
    return ScopeAdjustment(
        id=new_id(),
        created_at=_now(),
        action="flag_ticker",
        scope=ticker,
        reason=reason,
        trigger=f"event:{event_type}",
        severity=severity,
        ttl_minutes=FLAG_TTL_MINUTES,
    )
