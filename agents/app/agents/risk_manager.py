"""Risk Manager Agent - highest authority.

Subscribes to `signal` messages. For each one, applies position-sizing and
exposure rules and emits either an `approve` or `veto`. Veto wins -
Trade Execution only ever listens for `approve`.

Rules:
  - Veto if direction is "neutral" (no actionable bias)
  - Veto if the signal's strategy is paused by Adaptive Scope
  - Veto if the signal's ticker is flagged by Adaptive Scope
  - Veto if TCS below the user's threshold (raised by the regime posture)
  - Veto if too many open signals already (configurable cap)
  - Veto for everyone today if a user's daily loss limit has been hit
  - Veto for everyone if a safety kill-switch is tripped (Phase 8c)
  - Otherwise approve, forwarding strategy + stop/target geometry, with
    stops tightened by the current Adaptive Scope posture
"""

from __future__ import annotations

import asyncio
from collections import deque

from app.config import get_settings

from .base import Agent, AgentMessage


def _supabase():
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_role_key:
        return None
    try:
        from supabase import create_client
        return create_client(settings.supabase_url, settings.supabase_service_role_key)
    except Exception:
        return None


async def _find_rotation_candidate(
    user_id, incoming_tcs: int,
) -> dict | None:
    """When a signal is vetoed for the open-position cap, ask:
    which open position is the weakest fit, and would the incoming
    signal beat it cleanly? Returns a hint dict the UI can render as
    "Trim AAPL to take SOFI" guidance, or None when no clear swap.

    Pure advisory - this does NOT auto-close anything. Mike's pattern:
    surface the asymmetry, let the user pick the action.
    """
    if not user_id:
        return None
    client = _supabase()
    if not client:
        return None
    try:
        def _sync():
            return (
                client.table("paper_positions")
                .select("id, ticker, side, asset_type, quantity, "
                        "entry_price, stop_price, target_price, entry_at, "
                        "source_payload, peak_unrealized_pnl_usd")
                .eq("user_id", user_id)
                .eq("status", "open")
                .execute()
            )
        res = await asyncio.to_thread(_sync)
        rows = res.data or []
        if not rows:
            return None

        # Score each open position via position_health. Pick the
        # weakest (lowest effective TCS = entry TCS minus decay).
        from app.learning.position_health import compute_position_health
        weakest = None
        weakest_score = None
        for pos in rows:
            try:
                h = await compute_position_health(pos)
            except Exception:  # noqa: BLE001
                h = None
            if h is None or h.entry_tcs is None or h.current_tcs is None:
                continue
            # Effective TCS = current TCS (already decayed). Lower is weaker.
            if weakest_score is None or h.current_tcs < weakest_score:
                weakest = (pos, h)
                weakest_score = h.current_tcs

        if not weakest or weakest_score is None:
            return None

        # Only flag as a rotation when the incoming signal beats the
        # weakest by a clear margin (>= 75 TCS). Otherwise the swap
        # is noise.
        if incoming_tcs - weakest_score < 75:
            return None

        pos, h = weakest
        return {
            "position_id": pos["id"],
            "ticker": pos.get("ticker"),
            "current_tcs": h.current_tcs,
            "entry_tcs": h.entry_tcs,
            "tcs_decay_pct": h.tcs_decay_pct,
            "incoming_tcs": incoming_tcs,
            "gap": incoming_tcs - h.current_tcs,
            "recommendation": h.recommendation,
        }
    except Exception:  # noqa: BLE001
        return None


async def _users_in_daily_drawdown() -> set[str]:
    """Return user_ids whose today's realized loss meets/exceeds their limit."""
    client = _supabase()
    if not client:
        return set()

    def _sync():
        accounts = client.table("paper_accounts").select("user_id, today_realized_pnl_usd").execute()
        profiles = client.table("profiles").select("user_id, daily_loss_limit_usd").execute()
        return accounts.data or [], profiles.data or []

    accounts, profiles = await asyncio.to_thread(_sync)
    limit_by_user: dict[str, float] = {}
    for p in profiles:
        try:
            v = float(p.get("daily_loss_limit_usd") or 0)
            if v > 0:
                limit_by_user[p["user_id"]] = v
        except (TypeError, ValueError):
            pass

    drawdown: set[str] = set()
    for a in accounts:
        uid = a["user_id"]
        limit = limit_by_user.get(uid, 0)
        if limit <= 0:
            continue
        try:
            today = float(a.get("today_realized_pnl_usd") or 0)
        except (TypeError, ValueError):
            continue
        if today <= -limit:
            drawdown.add(uid)
    return drawdown


class RiskManagerAgent(Agent):
    name = "risk_manager"
    tick_interval_seconds = 0  # event-driven; never auto-ticks

    # Note: TCS minimum used to live here as a class default. It now
    # comes from `bot_settings.tcs_threshold` (per-user) via
    # `get_bot_settings(user_id).tcs_threshold` so the user's Bot Tuning
    # slider drives the gate. The dead constant is gone on purpose.
    MAX_OPEN_SIGNALS = 3
    DEFAULT_PCT_OF_ACCOUNT = 0.02

    def __init__(self) -> None:
        self._recent_approvals: deque[str] = deque(maxlen=8)

    async def tick(self) -> list[AgentMessage]:
        return []

    async def on_message(self, message: AgentMessage) -> list[AgentMessage]:
        if message.kind != "signal":
            return []

        tcs = int(message.payload.get("tcs", 0))
        direction = message.payload.get("direction", "neutral")
        ticker = message.payload.get("ticker", "?")
        strategy = message.payload.get("strategy", "default")
        stop_pct = message.payload.get("stop_pct")
        target_pct = message.payload.get("target_pct")

        # User-tunable thresholds from the Bot Tuning settings page.
        from app.runtime.settings import get_bot_settings
        # Per-user settings when the signal is user-scoped (#119);
        # the global row otherwise.
        cfg = get_bot_settings(message.payload.get("user_id"))
        min_tcs = cfg.tcs_threshold
        max_open = cfg.max_open_positions

        # Adaptive Scope - the news/regime self-tuner (Phase 7.5). The Risk
        # Manager is the single enforcement point: every signal flows
        # through here, so consulting scope here covers every strategy.
        from app.runtime.scope import get_scope
        scope = get_scope()

        if direction == "neutral":
            return [self._veto(ticker, tcs, "Neutral direction - no actionable bias")]

        # Paused strategy - a base name in the paused set pauses its
        # variants too (e.g. 'crypto' pauses crypto_scalp/swing/dca).
        if (strategy in scope.paused_strategies
                or strategy.split("_")[0] in scope.paused_strategies):
            return [self._veto(
                ticker, tcs,
                f"Strategy '{strategy}' paused by Adaptive Scope [{scope.regime}]")]

        # Flagged ticker - a recent material event on this name.
        if ticker in scope.flagged_tickers:
            return [self._veto(
                ticker, tcs,
                f"{ticker} flagged by Adaptive Scope - recent material event")]

        # Expert override: per-stock disable list. When the user has
        # turned off a ticker (e.g. "skip NVDA until earnings"),
        # Risk Manager vetoes every signal on it with the user's
        # reason in the note.
        try:
            from app.runtime.overrides import get_disabled_reason
            disabled_reason = await get_disabled_reason(
                message.payload.get("user_id"), ticker,
            )
            if disabled_reason:
                return [self._veto(
                    ticker, tcs,
                    f"{ticker} disabled in Expert overrides: {disabled_reason}")]
        except Exception:  # noqa: BLE001
            pass

        # Cycle-aware bump (Phase 13a). Mike's "think like a human" push:
        # directional plays close to earnings are riskier - IV is rich
        # so options trades pay better, but stock trades face a binary
        # event. Bump the TCS floor by +50 when within 3 days of
        # earnings to filter all but the strongest signals. Strategies
        # that EXPLICITLY want the earnings window (iv_crush_short)
        # bypass this bump.
        cycle = message.payload.get("cycle") or {}
        cycle_bump = 0
        cycle_reason = ""
        days_to_earnings = cycle.get("next_earnings_days")
        iv_env = cycle.get("iv_environment", "normal")
        cycle_aware_strategy = strategy in (
            "iv_crush_short", "dividend_capture_long",
        )
        if (
            isinstance(days_to_earnings, int)
            and 0 < days_to_earnings <= 3
            and not cycle_aware_strategy
        ):
            cycle_bump = 50
            cycle_reason = f" (earnings in {days_to_earnings}d +50)"
        elif iv_env == "earnings_day" and not cycle_aware_strategy:
            cycle_bump = 150
            cycle_reason = " (earnings TODAY +150)"

        # The confidence bar can be raised by the current regime posture
        # AND the cycle-aware bump from above.
        effective_min_tcs = min_tcs + scope.tcs_bump + cycle_bump
        if tcs < effective_min_tcs:
            extra = (
                f" (regime +{scope.tcs_bump}{cycle_reason})"
                if scope.tcs_bump or cycle_bump
                else ""
            )
            return [self._veto(
                ticker, tcs,
                f"TCS {tcs} below threshold {effective_min_tcs}{extra}")]

        if len(self._recent_approvals) >= max_open:
            # Mike 2026-06-01 capital recycling: the veto stands BUT we
            # attach a rotation hint so the user/UI can see which
            # weakest open position would free up the slot. Pure
            # advisory - we do not auto-close anything here.
            rotation_hint = await _find_rotation_candidate(
                message.payload.get("user_id"), tcs,
            )
            veto = self._veto(
                ticker, tcs,
                f"Open-signal cap reached ({max_open})",
            )
            if rotation_hint:
                veto.payload["rotation_candidate"] = rotation_hint
            return [veto]

        # Daily-drawdown gate - veto if ANY user is over their loss limit.
        drawdown = await _users_in_daily_drawdown()
        if drawdown:
            return [self._veto(
                ticker, tcs,
                f"Daily loss limit hit for {len(drawdown)} user(s) - pausing signals"
            )]

        # Safety kill-switches (Phase 8c) - daily/weekly drawdown, losing
        # streak, broker rejects. Any trip halts every new signal.
        from app.paper.killswitch import check_all as check_killswitches
        ks = await check_killswitches(_supabase())
        if ks.halted:
            return [self._veto(
                ticker, tcs, f"Kill-switch [{ks.scope}] - {ks.reason}")]

        # Market regime + symbol-quality filter (Phase 8d) - stocks only.
        # Crypto trades 24/7 and is not tied to the US equity session.
        # Read the crypto set from COIN_MAP so the ISO 20022-aligned
        # coin expansion (Mike 2026-05-31) is picked up automatically.
        from app.data.candles import COIN_MAP as _COIN_MAP
        if ticker.upper() not in _COIN_MAP:
            from app.strategies.market_filter import (
                get_market_bias, direction_blocked, liquidity_check,
                overextension_check, spread_quality_check,
            )
            from app.data.candles import fetch_candles_for
            side = "long" if direction == "bullish" else "short"
            blocked = direction_blocked(await get_market_bias(), side)
            if blocked:
                return [self._veto(ticker, tcs, blocked)]
            stock_candles = await fetch_candles_for(ticker, "stock")
            liq = liquidity_check(stock_candles)
            if liq:
                return [self._veto(ticker, tcs, liq)]
            ext = overextension_check(stock_candles)
            if ext:
                return [self._veto(ticker, tcs, ext)]
            spread = await spread_quality_check(ticker)
            if spread:
                return [self._veto(ticker, tcs, spread)]
        else:
            # Per-coin daily loss limit (QW6) - crypto only. Benches a
            # single coin without halting the rest of the book.
            from app.paper.killswitch import coin_loss_halt
            coin_veto = await coin_loss_halt(_supabase(), ticker)
            if coin_veto:
                return [self._veto(ticker, tcs, coin_veto)]

        self._recent_approvals.append(ticker)
        approve_payload: dict = {
            "ticker": ticker,
            "direction": direction,
            "tcs": tcs,
            "position_pct": self.DEFAULT_PCT_OF_ACCOUNT,
            "strategy": strategy,
            "reason": f"TCS {tcs} clears threshold; {direction} bias [{strategy}]",
        }
        # Adaptive Scope can tighten stops in rougher regimes.
        if stop_pct is not None:
            tightened = round(float(stop_pct) * scope.stop_multiplier, 4)
            approve_payload["stop_pct"] = tightened
            if scope.stop_multiplier < 1.0:
                approve_payload["stop_adjusted"] = True
                approve_payload["reason"] += f"; stop tightened x{scope.stop_multiplier} [{scope.regime}]"
        if target_pct is not None:
            approve_payload["target_pct"] = target_pct

        return [
            AgentMessage(
                agent=self.name,
                kind="approve",
                confidence=tcs / 1000.0,
                payload=approve_payload,
            )
        ]

    def _veto(self, ticker: str, tcs: int, reason: str) -> AgentMessage:
        return AgentMessage(
            agent=self.name,
            kind="veto",
            confidence=1.0,
            payload={"ticker": ticker, "tcs": tcs, "reason": reason},
        )
