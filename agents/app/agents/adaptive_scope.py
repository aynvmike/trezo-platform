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
import logging

_log = logging.getLogger(__name__)

from app.config import get_settings
from app.strategies.adaptive import (
    event_adjustment, regime_posture, ScopeAdjustment,
)
from app.strategies.regime import read_market_regime
from app.runtime.scope import scope_state

from .base import Agent, AgentMessage


def _book_ids() -> list[str]:
    from app.brokers.accounts import load_accounts
    return list(dict.fromkeys(str(a.user_id) for a in load_accounts()
                              if getattr(a, "user_id", None)))


def _autonomy_mode(user_id: str) -> str:
    if not user_id:
        return "suggest"
    try:
        from app.runtime.settings import get_bot_settings, is_fallback_settings
        cfg = get_bot_settings(user_id)
        if is_fallback_settings(cfg):
            return "suggest"  # unknown authority can propose, never apply controls
        return getattr(cfg, "autonomy_mode", "guarded") or "guarded"
    except Exception:  # noqa: BLE001
        return "suggest"


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
    if not adj.user_id:
        return
    row = {
        "user_id": adj.user_id,
        "created_at": adj.created_at,
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
        table = client.table("strategy_scope_adjustments")
        if adj.status in ("expired", "dismissed"):
            return (table.update({"status": adj.status}).eq("user_id", adj.user_id)
                    .eq("adjustment_id", adj.id).execute())
        return table.insert(row).execute()

    try:
        await asyncio.to_thread(_sync)
    except Exception as exc:  # noqa: BLE001
        _log.warning("Scope audit write failed for book %s: %s", adj.user_id, exc)


_CONSUMED_IDS: set[tuple[str, str]] = set()


def _adj_from_row(row: dict) -> ScopeAdjustment:
    """Rebuild a ScopeAdjustment from a strategy_scope_adjustments row."""
    return ScopeAdjustment(
        user_id=str(row.get("user_id") or ""),
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


async def _pull_approved(user_id: str) -> list:
    """User-approved adjustments (status='applied') not yet loaded into the
    live scope this session. Looks back 24h so a restart rebuilds the longest-lived ticker flags."""
    if not user_id:
        return []
    client = _supabase()
    if not client:
        return []
    from datetime import datetime, timedelta, timezone
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

    def _q():
        return (client.table("strategy_scope_adjustments")
                .select("*").eq("status", "applied").eq("user_id", user_id)
                .gte("created_at", since)
                .order("created_at", desc=True).limit(200).execute())
    try:
        res = await asyncio.to_thread(_q)
    except Exception:  # noqa: BLE001
        return []
    out = []
    for row in reversed(res.data or []):
        rid = str(row.get("id") or row.get("adjustment_id") or "")
        if not rid or str(row.get("user_id") or "") != user_id:
            continue
        if (user_id, rid) in _CONSUMED_IDS:
            continue
        _CONSUMED_IDS.add((user_id, rid))
        adj = _adj_from_row(row)
        try:
            created = datetime.fromisoformat(adj.created_at)
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if created + timedelta(minutes=adj.ttl_minutes) <= datetime.now(timezone.utc):
                continue
        except (TypeError, ValueError):
            continue  # invalid timestamps cannot acquire fresh control TTLs
        out.append(adj)
    return out


class AdaptiveScopeAgent(Agent):
    name = "adaptive_scope"
    tick_interval_seconds = 600

    async def tick(self) -> list[AgentMessage]:
        out: list[AgentMessage] = []
        books = _book_ids()
        if not books:
            return [AgentMessage(agent=self.name, kind="info", payload={
                "event": "scope_no_books", "note": "No routable books; no scope controls applied"})]
        for user_id in books:
            state = scope_state.for_book(user_id)
            for adj in scope_state.expire_stale(user_id):
                await _persist(adj)
                out.append(AgentMessage(agent=self.name, kind="info", payload={
                    "user_id": user_id, "note": "Scope adjustment expired",
                    "scope": adj.scope, "trigger": adj.trigger}))
            # Restore this book's still-valid controls after restart. Query
            # ownership is enforced again locally, so old global rows never act.
            for adj in await _pull_approved(user_id):
                if adj.action == "flag_ticker":
                    state.flag_ticker(adj)
                elif adj.action == "set_posture":
                    state.set_posture(adj)
                else:
                    continue
                out.append(AgentMessage(agent=self.name, kind="scope", payload={
                    "user_id": user_id, "note": "Book scope control restored",
                    "action": adj.action, "scope": adj.scope, "reason": adj.reason}))

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

        for user_id in books:
            mode = _autonomy_mode(user_id)
            state = scope_state.for_book(user_id)
            posture = regime_posture(read)
            posture.user_id = user_id
            posture.status = "suggested" if mode == "suggest" else "applied"
            cur = state.current_posture()
            same = (cur is not None
                    and cur.stop_multiplier == posture.stop_multiplier
                    and cur.tcs_bump == posture.tcs_bump
                    and cur.paused_strategies == posture.paused_strategies
                    and cur.trigger == posture.trigger)
            if same:
                continue  # a quiet book must not skip its siblings
            if mode != "suggest":
                state.set_posture(posture)
            await _persist(posture)
            verb = "suggested" if mode == "suggest" else "set"
            out.append(AgentMessage(
                agent=self.name, kind="info" if mode == "suggest" else "scope",
                confidence=getattr(read, "confidence", 0.5), payload={
                    "user_id": user_id, "note": f"Regime posture {verb}",
                    "regime": read.regime, "autonomy_mode": mode,
                    "stop_multiplier": posture.stop_multiplier,
                    "tcs_bump": posture.tcs_bump,
                    "paused_strategies": list(posture.paused_strategies),
                    "summary": read.summary}))
        return out

    async def on_message(self, message: AgentMessage) -> list[AgentMessage]:
        if message.kind != "event":
            return []
        books = _book_ids()
        event_book = str(message.payload.get("user_id") or "")
        if event_book:
            books = [uid for uid in books if uid == event_book]
        out = []
        for user_id in books:
            mode = _autonomy_mode(user_id)
            adj = event_adjustment(message.payload, mode=mode)
            if adj is None:
                continue
            adj.user_id = user_id
            if mode == "suggest":
                adj.status = "suggested"
                await _persist(adj)
                out.append(AgentMessage(agent=self.name, kind="info", payload={
                    "user_id": user_id,
                    "note": "Scope change suggested (awaiting approval)",
                    "action": adj.action, "scope": adj.scope, "reason": adj.reason}))
                continue
            applied = scope_state.for_book(user_id).flag_ticker(adj)
            if not applied:
                adj.status = "suggested"
            await _persist(adj)
            out.append(AgentMessage(
                agent=self.name, kind="scope" if applied else "info",
                confidence=0.9 if applied else 0.0, payload={
                    "user_id": user_id,
                    "note": ("Ticker flagged - Risk Manager will veto its signals"
                             if applied else "Ticker-flag cap reached - flag not applied"),
                    "action": adj.action, "scope": adj.scope,
                    "trigger": adj.trigger, "reason": adj.reason}))
        return out
