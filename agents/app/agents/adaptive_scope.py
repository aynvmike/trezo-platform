"""Adaptive Scope Agent - Trezo's news- and regime-aware self-tuner.

Phase 7.5. The 13th agent. Two jobs:

  tick (every 10 min):
    - read the market regime (SPY proxy)
    - translate it into a market-wide posture: how tight to run stops,
      how high to set the confidence bar, which strategies to pause
    - expire any scope adjustments past their TTL

  on_message (event-driven):
    - react to `event` messages from Market Sentiment and Research
    - when a material event hits a ticker, flag that ticker so the Risk
      Manager stops approving signals on it

Autonomy mode (Bot Tuning) decides how much it may do on its own:
    suggest  - record recommendations, change nothing
    guarded  - apply risk-reducing moves within hard guardrails (default)
    full     - also act on lower-severity events

Every adjustment is persisted (best-effort) to strategy_scope_adjustments
for the dashboard and the audit trail.

Macro overlay (2026-05-29): the regime read goes through the macro
adapter (`app.data.macro`) before posture is computed. When the active
backend supplies enough data to call a clear regime, we override the
stock-price-derived read. Falls back silently when no backend is
configured. See `app/data/macro/base.py` for the licensing story.
"""

from __future__ import annotations

import asyncio

from app.config import get_settings
from app.strategies.adaptive import (
    event_adjustment, regime_posture, ScopeAdjustment,
)
from app.strategies.regime import read_market_regime
from app.runtime.scope import scope_state

from .base import Agent, AgentMessage


def _autonomy_mode() -> str:
    try:
        from app.runtime.settings import get_bot_settings
        return getattr(get_bot_settings(), "autonomy_mode", "guarded") or "guarded"
    except Exception:  # noqa: BLE001
        return "guarded"


def _supabase():
    s = get_settings()
    if not s.supabase_url or not s.supabase_service_role_key:
        return None
    try:
        from supabase import create_client
        return create_client(s.supabase_url, s.supabase_service_role_key)
    except Exception:  # noqa: BLE001
        return None


async def _persist(adj) -> None:
    """Best-effort write to strategy_scope_adjustments. Silent if the
    table is not there yet (migration 0013) or Supabase is unconfigured."""
    client = _supabase()
    if not client:
        return
    row = {
        "adjustment_id": adj.id,
        "action": adj.action,
        "scope": adj.scope,
        "reason": adj.reason,
        "trigger": adj.trigger,
        "severity": adj.severity,
        "status": adj.status,
        "stop_multiplier": adj.stop_multiplier,
        "tcs_bump": adj.tcs_bump,
        "paused_strategies": list(adj.paused_strategies),
        "ttl_minutes": adj.ttl_minutes,
    }

    def _sync():
        return client.table("strategy_scope_adjustments").insert(row).execute()

    try:
        await asyncio.to_thread(_sync)
    except Exception:  # noqa: BLE001
        pass


_CONSUMED_IDS: set[str] = set()


def _adj_from_row(row: dict) -> ScopeAdjustment:
    """Rebuild a ScopeAdjustment from a strategy_scope_adjustments row."""
    return ScopeAdjustment(
        id=str(row.get("adjustment_id") or row.get("id") or ""),
        created_at=str(row.get("created_at") or ""),
        action=str(row.get("action") or "set_posture"),
        scope=str(row.get("scope") or "market"),
        reason=str(row.get("reason") or ""),
        trigger=str(row.get("trigger") or ""),
        severity=str(row.get("severity") or "low"),
        ttl_minutes=int(row.get("ttl_minutes") or 360),
        status="applied",
        stop_multiplier=float(row.get("stop_multiplier") or 1.0),
        tcs_bump=int(row.get("tcs_bump") or 0),
        paused_strategies=tuple(row.get("paused_strategies") or ()),
    )


async def _pull_approved() -> list:
    """User-approved adjustments (status='applied') not yet loaded into the
    live scope this session. Looks back 12h so a restart rebuilds scope."""
    client = _supabase()
    if not client:
        return []
    from datetime import datetime, timedelta, timezone
    since = (datetime.now(timezone.utc) - timedelta(hours=12)).isoformat()

    def _q():
        return (client.table("strategy_scope_adjustments")
                .select("*").eq("status", "applied")
                .gte("created_at", since)
                .order("created_at", desc=True).limit(50).execute())
    try:
        res = await asyncio.to_thread(_q)
    except Exception:  # noqa: BLE001
        return []
    out = []
    for row in (res.data or []):
        rid = str(row.get("id") or row.get("adjustment_id") or "")
        if not rid or rid in _CONSUMED_IDS:
            continue
        _CONSUMED_IDS.add(rid)
        out.append(_adj_from_row(row))
    return out


class AdaptiveScopeAgent(Agent):
    name = "adaptive_scope"
    tick_interval_seconds = 600

    async def tick(self) -> list[AgentMessage]:
        out: list[AgentMessage] = []
        mode = _autonomy_mode()

        for adj in scope_state.expire_stale():
            await _persist(adj)
            out.append(AgentMessage(
                agent=self.name, kind="info",
                payload={"note": "Scope adjustment expired",
                         "scope": adj.scope, "trigger": adj.trigger},
            ))

        if mode == "suggest":
            for adj in await _pull_approved():
                if adj.action == "flag_ticker":
                    scope_state.flag_ticker(adj)
                else:
                    scope_state.set_posture(adj)
                out.append(AgentMessage(
                    agent=self.name, kind="scope", confidence=1.0,
                    payload={"note": "User-approved scope change applied",
                             "action": adj.action, "scope": adj.scope,
                             "reason": adj.reason},
                ))

        # Stock-price-derived regime.
        read = await read_market_regime()

        # Macro overlay via the adapter (see `app.data.macro`).
        # Silently no-op when no backend is configured.
        try:
            from app.data.macro import (
                get_macro_reading, classify_macro_regime,
            )
            macro_reading = await get_macro_reading()
            macro_regime, macro_why = classify_macro_regime(macro_reading)
            if macro_regime == "risk_off" and read.regime not in (
                "risk_off", "high_volatility",
            ):
                read.regime = "risk_off"
                read.summary = (
                    f"Macro overlay: {macro_why} "
                    f"(stock price read was {getattr(read, 'regime', '?')})"
                )
            elif macro_regime == "growth" and read.regime == "choppy":
                read.regime = "trending_up"
                read.summary = (
                    f"Macro overlay: {macro_why} "
                    f"(upgrading choppy stock-read to trending_up)"
                )
        except Exception:  # noqa: BLE001
            pass

        posture = regime_posture(read)
        posture.status = "suggested" if mode == "suggest" else "applied"

        cur = scope_state.current_posture() if hasattr(scope_state, "current_posture") else None
        same = (
            cur is not None
            and getattr(cur, "scope", None) == posture.scope
            and float(getattr(cur, "stop_multiplier", 1.0)) == float(posture.stop_multiplier)
            and int(getattr(cur, "tcs_bump", 0)) == int(posture.tcs_bump)
            and tuple(getattr(cur, "paused_strategies", ()) or ()) == tuple(posture.paused_strategies or ())
            and getattr(cur, "trigger", None) == posture.trigger
        )
        if same:
            return out

        if mode != "suggest":
            scope_state.set_posture(posture)
        await _persist(posture)

        verb = "suggested" if mode == "suggest" else "set"
        out.append(AgentMessage(
            agent=self.name,
            kind=("info" if mode == "suggest" else "scope"),
            confidence=getattr(read, "confidence", 0.5),
            payload={
                "note": f"Regime posture {verb}",
                "regime": read.regime,
                "autonomy_mode": mode,
                "stop_multiplier": posture.stop_multiplier,
                "tcs_bump": posture.tcs_bump,
                "paused_strategies": list(posture.paused_strategies),
                "summary": read.summary,
            },
        ))
        return out

    async def on_message(self, message: AgentMessage) -> list[AgentMessage]:
        if message.kind != "event":
            return []
        mode = _autonomy_mode()
        adj = event_adjustment(message.payload, mode=mode)
        if adj is None:
            return []

        if mode == "suggest":
            adj.status = "suggested"
            await _persist(adj)
            return [AgentMessage(
                agent=self.name, kind="info",
                payload={"note": "Scope change suggested (awaiting approval)",
                         "action": adj.action, "scope": adj.scope,
                         "reason": adj.reason},
            )]

        applied = scope_state.flag_ticker(adj)
        await _persist(adj)
        if not applied:
            return [AgentMessage(
                agent=self.name, kind="info",
                payload={"note": "Ticker-flag cap reached - flag not applied",
                         "scope": adj.scope},
            )]
        return [AgentMessage(
            agent=self.name, kind="scope", confidence=0.9,
            payload={"note": "Ticker flagged - Risk Manager will veto its signals",
                     "action": adj.action, "scope": adj.scope,
                     "trigger": adj.trigger, "reason": adj.reason},
        )]
