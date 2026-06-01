"""Position Monitor Agent.

Ticks every 30 seconds. For every open paper position across all users:
  - Fetches the current price
  - Closes internal positions on a stop or target hit
  - Applies day-trade management to intraday strategies (Phase 8e):
    force-exit near the close (3:45 PM ET), a 90-minute max hold, and a
    75-minute stagnation check (exit if not yet at 0.25R)
  - Reconciles Alpaca-routed positions (Phase 8g): when Alpaca's bracket
    order has closed one, the Trezo tracking row is marked closed
  - Emits a `close` message for each closure
  - Triggers the Daily Profit Lock check after closures
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.config import get_settings
from app.data.candles import fetch_candles_for
from app.paper.engine import close_position, check_and_lock_profit
from app.strategies.extended import SWING_MAX_HOLD_DAYS

from .base import Agent, AgentMessage

# Day-trade management thresholds (Phase 8e).
MAX_HOLD_MINUTES = 90
STAGNATION_MINUTES = 75
STAGNATION_R = 0.25


def _supabase():
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_role_key:
        return None
    try:
        from supabase import create_client
        return create_client(settings.supabase_url, settings.supabase_service_role_key)
    except Exception:
        return None


async def _latest_price(ticker: str, asset_type: str) -> float | None:
    """Best-effort latest price from candle data. Returns the most recent close."""
    candles = await fetch_candles_for(ticker, asset_type if asset_type != "option" else "stock")
    if not candles:
        return None
    return float(candles[-1].close)


def _minutes_since(iso_ts) -> float:
    """Minutes elapsed since an ISO timestamp. 0 if missing or unparseable."""
    if not iso_ts:
        return 0.0
    try:
        t = datetime.fromisoformat(str(iso_ts).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - t).total_seconds() / 60.0
    except Exception:  # noqa: BLE001
        return 0.0


class PositionMonitorAgent(Agent):
    name = "position_monitor"
    tick_interval_seconds = 30

    async def tick(self) -> list[AgentMessage]:
        client = _supabase()
        if not client:
            return [AgentMessage(agent=self.name, kind="error",
                                 payload={"error": "Supabase not configured"})]

        def _sync():
            return (
                client.table("paper_positions")
                .select("id, user_id, ticker, asset_type, side, quantity, entry_price, stop_price, target_price, strategy, entry_at, broker, close_requested")
                .eq("status", "open")
                .execute()
            )

        res = await asyncio.to_thread(_sync)
        rows = res.data or []

        out: list[AgentMessage] = []
        affected_users: set[str] = set()
        price_cache: dict[str, float] = {}
        alpaca_managed = 0
        alpaca_reconciled = 0

        # Phase 8g: which symbols Alpaca still holds. None = could not check
        # (so a transient failure never closes a position by mistake).
        alpaca_held = None
        if any(r.get("broker") == "alpaca" for r in rows):
            try:
                from app.brokers.alpaca import alpaca_configured, get_open_symbols
                if alpaca_configured():
                    alpaca_held = await get_open_symbols()
            except Exception:  # noqa: BLE001
                alpaca_held = None

        async def _price(tk: str, at: str) -> float | None:
            key = f"{tk}:{at}"
            if key not in price_cache:
                p = await _latest_price(tk, at)
                if p is not None:
                    price_cache[key] = p
            return price_cache.get(key)

        for r in rows:
            tk = r["ticker"]
            at = r["asset_type"]

            # --- Alpaca-routed positions (Phase 8b / 8g) -------------------
            if r.get("broker") == "alpaca":
                if alpaca_held is not None and tk.upper() not in alpaca_held:
                    # Alpaca's bracket order closed it - reconcile our books.
                    price = await _price(tk, at)
                    if price is not None:
                        from app.paper.engine import record_external_close
                        fill = await record_external_close(r["user_id"], r["id"], price)
                        if fill.ok:
                            alpaca_reconciled += 1
                            affected_users.add(r["user_id"])
                            out.append(AgentMessage(
                                agent=self.name, kind="close", confidence=1.0,
                                payload={
                                    "user_id": r["user_id"], "ticker": tk,
                                    "side": r["side"], "reason": "alpaca_bracket",
                                    "exit_price": fill.fill_price,
                                    "realized_pnl_usd": fill.realized_pnl_usd,
                                    "position_id": r["id"], "broker": "alpaca",
                                }))
                else:
                    # Swing time stop (Phase 10c): an Extended position
                    # held past its multi-day window is closed at market
                    # on Alpaca; the next tick reconciles the Trezo row
                    # once Alpaca drops the symbol from its open set.
                    strat_a = (r.get("strategy") or "").lower()
                    held_days = _minutes_since(r.get("entry_at")) / 1440.0
                    if strat_a.startswith("extended") and held_days >= SWING_MAX_HOLD_DAYS:
                        from app.brokers.alpaca import liquidate_position
                        _liq, liq_err = await liquidate_position(tk)
                        out.append(AgentMessage(
                            agent=self.name, kind="info",
                            payload={"user_id": r["user_id"], "ticker": tk,
                                     "note": ("Extended swing time stop - Alpaca "
                                              "position closed at market"
                                              + (f" (error: {liq_err})" if liq_err else "")),
                                     "position_id": r["id"], "broker": "alpaca"}))
                    else:
                        alpaca_managed += 1
                continue

            # --- Internal paper positions ----------------------------------
            price = await _price(tk, at)
            if price is None:
                continue

            side   = r["side"]
            stop   = float(r["stop_price"]) if r.get("stop_price") else None
            target = float(r["target_price"]) if r.get("target_price") else None

            close_reason: str | None = None
            close_detail = ""
            # QW1: an explicit user close request takes priority.
            if r.get("close_requested"):
                close_reason, close_detail = "manual", "manual_close"
            if close_reason is None:
                if side == "long":
                    if stop is not None and price <= stop:
                        close_reason = "stop"
                    elif target is not None and price >= target:
                        close_reason = "target"
                else:  # short
                    if stop is not None and price >= stop:
                        close_reason = "stop"
                    elif target is not None and price <= target:
                        close_reason = "target"

            # Day-trade management (Phase 8e) for intraday strategies.
            strat = (r.get("strategy") or "").lower()
            if not close_reason and (strat.startswith("stms") or strat.startswith("orb")):
                now = datetime.now(timezone.utc)
                held = _minutes_since(r.get("entry_at"))
                if strat.startswith("stms") and now.hour >= 15:
                    close_reason, close_detail = "time", "stms_11am_stop"
                elif now.hour > 19 or (now.hour == 19 and now.minute >= 45):
                    close_reason, close_detail = "eod", "force_exit_345pm"
                elif held >= MAX_HOLD_MINUTES:
                    close_reason, close_detail = "time", "max_hold_90min"
                elif held >= STAGNATION_MINUTES and stop is not None:
                    r_dist = abs(float(r["entry_price"]) - stop)
                    if r_dist > 0:
                        entry = float(r["entry_price"])
                        favorable = (price - entry) if side == "long" else (entry - price)
                        if favorable < STAGNATION_R * r_dist:
                            close_reason, close_detail = "time", "stagnation_75min"

            # Multi-day time stop for swing strategies (Phase 10c).
            # Extended positions are held across sessions, then closed
            # once they pass their swing window (~5 trading days).
            if not close_reason and strat.startswith("extended"):
                if _minutes_since(r.get("entry_at")) / 1440.0 >= SWING_MAX_HOLD_DAYS:
                    close_reason, close_detail = "time", "swing_time_stop"

            if close_reason:
                fill = await close_position(r["user_id"], r["id"], price, reason=close_reason)
                if fill.ok:
                    affected_users.add(r["user_id"])
                    out.append(AgentMessage(
                        agent=self.name,
                        kind="close",
                        confidence=1.0,
                        payload={
                            "user_id": r["user_id"],
                            "ticker": tk,
                            "side": side,
                            "reason": close_detail or close_reason,
                            "exit_price": fill.fill_price,
                            "realized_pnl_usd": fill.realized_pnl_usd,
                            "position_id": r["id"],
                        },
                    ))

        # After closures, evaluate Daily Profit Lock for each affected user.
        for user_id in affected_users:
            lock = await check_and_lock_profit(user_id)
            if lock:
                out.append(AgentMessage(
                    agent=self.name,
                    kind="alert",
                    confidence=1.0,
                    payload={"user_id": user_id, "event": "daily_profit_lock", **lock},
                ))

        if not out:
            return [AgentMessage(agent=self.name, kind="info",
                                 payload={"open_positions": len(rows),
                                          "checked_prices": len(price_cache),
                                          "alpaca_managed": alpaca_managed,
                                          "alpaca_reconciled": alpaca_reconciled})]
        return out
