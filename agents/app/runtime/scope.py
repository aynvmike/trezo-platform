"""Live adaptive-scope state — what the Risk Manager reads on every signal.

Phase 7.5. The AdaptiveScopeAgent writes adjustments here; the Risk
Manager reads the effective ScopeView and enforces it. State is in-memory
and process-local (consistent with the rest of the agent runtime);
adjustments are also persisted to Supabase for the dashboard and audit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.strategies.adaptive import ScopeAdjustment, MAX_FLAGGED_TICKERS


@dataclass(frozen=True)
class ScopeView:
    """The effective scope the Risk Manager enforces right now."""

    stop_multiplier: float
    tcs_bump: int
    flagged_tickers: frozenset[str]
    paused_strategies: frozenset[str]
    regime: str
    note: str


def _parse(ts: str) -> datetime:
    try:
        d = datetime.fromisoformat(ts)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        return datetime.now(timezone.utc)


class _ScopeState:
    def __init__(self) -> None:
        self._posture: ScopeAdjustment | None = None
        self._flags: dict[str, ScopeAdjustment] = {}
        self._regime: str = "choppy"

    def expire_stale(self) -> list[ScopeAdjustment]:
        """Drop adjustments past their TTL. Returns the ones expired."""
        now = datetime.now(timezone.utc)
        expired: list[ScopeAdjustment] = []
        if self._posture is not None:
            end = _parse(self._posture.created_at) + timedelta(
                minutes=self._posture.ttl_minutes)
            if now >= end:
                self._posture.status = "expired"
                expired.append(self._posture)
                self._posture = None
        for ticker, adj in list(self._flags.items()):
            end = _parse(adj.created_at) + timedelta(minutes=adj.ttl_minutes)
            if now >= end:
                adj.status = "expired"
                expired.append(adj)
                del self._flags[ticker]
        return expired

    def set_posture(self, adj: ScopeAdjustment) -> None:
        adj.status = "applied"
        self._posture = adj
        self._regime = adj.trigger.split(":")[-1]

    def current_posture(self):
        """Return the active posture adjustment (or None). Used by
        Adaptive Scope to dedupe — don't re-emit if posture hasn't moved."""
        return self._posture

    def flag_ticker(self, adj: ScopeAdjustment) -> bool:
        """Apply a ticker flag. False if the cap is already hit."""
        if adj.scope in self._flags:
            adj.status = "applied"
            self._flags[adj.scope] = adj  # refresh the TTL
            return True
        if len(self._flags) >= MAX_FLAGGED_TICKERS:
            return False
        adj.status = "applied"
        self._flags[adj.scope] = adj
        return True

    def clear_flag(self, ticker: str) -> bool:
        return self._flags.pop(ticker.upper(), None) is not None

    def active(self) -> list[ScopeAdjustment]:
        out: list[ScopeAdjustment] = []
        if self._posture is not None:
            out.append(self._posture)
        out.extend(self._flags.values())
        return out

    def view(self) -> ScopeView:
        p = self._posture
        return ScopeView(
            stop_multiplier=(p.stop_multiplier if p else 1.0),
            tcs_bump=(p.tcs_bump if p else 0),
            flagged_tickers=frozenset(self._flags.keys()),
            paused_strategies=frozenset(p.paused_strategies if p else ()),
            regime=self._regime,
            note=(p.reason if p else "No active posture — baseline scope."),
        )


scope_state = _ScopeState()


def get_scope() -> ScopeView:
    """The effective scope right now — call this from the Risk Manager."""
    return scope_state.view()
