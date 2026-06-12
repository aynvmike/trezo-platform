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


def _decide_time_stop(
    r: dict,
    side: str,
    price: float,
    stop: float | None,
) -> tuple[str | None, str]:
    """Pure function: given a row + current price, decide whether a
    time-based exit fires. Returns (close_reason, close_detail) when
    triggered, else (None, "").

    Time-stop rules (unchanged from prior internal-only logic, lifted
    out so both branches can apply them):
      - STMS strategies: force-exit after 11:00 ET (UTC hour >= 15
        check preserved from original code; see TODO below).
      - Any intraday strategy past 3:45 PM ET (force_exit_345pm).
      - 90-minute max hold for STMS/ORB intraday.
      - 75-minute stagnation if move < 0.25R against entry.

    TODO: the original hour comparisons use `now.hour >= 15` which
    only matches UTC; ET-correctness is a separate hardening task.
    Preserving the comparisons here to avoid behavior drift.
    """
    strat = (r.get("strategy") or "").lower()
    if not (strat.startswith("stms") or strat.startswith("orb")):
        return None, ""

    now = datetime.now(timezone.utc)
    held = _minutes_since(r.get("entry_at"))

    if strat.startswith("stms") and now.hour >= 15:
        return "time", "stms_11am_stop"
    if now.hour > 19 or (now.hour == 19 and now.minute >= 45):
        return "eod", "force_exit_345pm"
    if held >= MAX_HOLD_MINUTES:
        return "time", "max_hold_90min"
    if held >= STAGNATION_MINUTES and stop is not None:
        r_dist = abs(float(r.get("entry_price") or 0) - stop)
        if r_dist > 0:
            entry = float(r.get("entry_price") or 0)
            favorable = (price - entry) if side == "long" else (entry - price)
            if favorable < STAGNATION_R * r_dist:
                return "time", "stagnation_75min"

    return None, ""


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


_naked_checked_at: dict[str, float] = {}
_naked_alerted_at: dict[str, float] = {}
_NAKED_CHECK_EVERY_S = 600    # poll Alpaca orders at most every 10 min/symbol
_NAKED_ALERT_EVERY_S = 3600   # re-alert at most hourly/symbol


async def _naked_position_check(ticker: str, row: dict) -> dict | None:
    """Return an alert payload when an Alpaca-held STOCK position has no
    open exit orders (expired day-TIF bracket legs). Throttled per
    symbol; never raises."""
    import time as _time
    now_s = _time.time()
    if now_s - _naked_checked_at.get(ticker, 0.0) < _NAKED_CHECK_EVERY_S:
        return None
    _naked_checked_at[ticker] = now_s
    try:
        from app.brokers.alpaca import get_open_orders_for
        orders = await get_open_orders_for(ticker)
    except Exception:  # noqa: BLE001
        return None
    if orders is None or len(orders) > 0:
        return None  # could not check, or legs are alive -- all fine
    if now_s - _naked_alerted_at.get(ticker, 0.0) < _NAKED_ALERT_EVERY_S:
        return None
    _naked_alerted_at[ticker] = now_s
    return {
        "user_id": row.get("user_id"),
        "ticker": ticker,
        "position_id": row.get("id"),
        "broker": "alpaca",
        "event": "naked_position",
        "note": (
            f"{ticker} is held at Alpaca with NO open exit orders -- its "
            f"bracket legs likely expired at a previous close (day TIF). "
            f"The broker will not stop this position out. Re-arm "
            f"protection or close it manually from /dashboard/paper."
        ),
    }


class PositionMonitorAgent(Agent):
    name = "position_monitor"
    tick_interval_seconds = 60  # Throttled 2026-06-05 (was 30) to cut API load

    # Task #32: auto-reconcile stocks every ~60 min (60 ticks * 60s).
    # Counter is class-level - ticks are sequential so no race risk.
    # Task #6 (2026-06-11): also fire on tick 2 after restart so
    # phantom positions don't linger up to an hour after every restart.
    _recon_tick_counter: int = 0
    _RECON_EVERY_N_TICKS: int = 60
    _did_initial_reconcile: bool = False

    async def tick(self) -> list[AgentMessage]:
        # Task #32: every 30 min, sync Trezo's open stock positions against
        # Alpaca truth. Catches manual closes / phantoms within 30 min.
        type(self)._recon_tick_counter += 1
        # Task #6 (2026-06-11): fire reconcile on tick 2 after restart
        # so phantom positions don't linger up to an hour. Then revert
        # to the every-60-ticks cadence.
        is_initial = (
            not type(self)._did_initial_reconcile
            and type(self)._recon_tick_counter >= 2
        )
        is_scheduled = (
            type(self)._recon_tick_counter % type(self)._RECON_EVERY_N_TICKS == 0
        )
        if is_initial or is_scheduled:
            try:
                from app.paper.stocks_reconcile import reconcile_stocks_all_users
                result = await reconcile_stocks_all_users()
                type(self)._did_initial_reconcile = True
                if result.get("ok") and (
                    result.get("closed", 0)
                    or result.get("updated", 0)
                    or result.get("inserted", 0)
                ):
                    return [AgentMessage(
                        agent=self.name, kind="info",
                        payload={
                            "event": "stocks_auto_reconcile",
                            "closed": result.get("closed", 0),
                            "updated": result.get("updated", 0),
                            "inserted": result.get("inserted", 0),
                            "users_touched": result.get("users_touched", 0),
                        },
                    )]
            except Exception as e:  # noqa: BLE001
                # Never let reconcile failure block the rest of the tick.
                logger_msg = f"auto reconcile failed: {str(e)[:160]}"
                return [AgentMessage(agent=self.name, kind="error",
                                     payload={"error": logger_msg})]

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
                # --- Crypto exits (Task #10 fix, 2026-06-11) ---------------
                # Alpaca crypto has NO native bracket order, so stops and
                # targets are enforced client-side right here -- exactly
                # what Trade Execution's docstring promises. Membership
                # checks need pair variants because Alpaca reports crypto
                # as 'BTCUSD'/'BTC/USD' while Trezo rows store 'BTC';
                # without that, every crypto row phantom-closes on tick 1
                # while Alpaca keeps holding the coins.
                if at == "crypto":
                    from app.brokers.alpaca import (
                        crypto_symbol_variants,
                        liquidate_position,
                    )
                    if (alpaca_held is not None
                            and not (crypto_symbol_variants(tk)
                                     & alpaca_held)):
                        # Genuinely gone at the broker -> reconcile books.
                        price_c = await _price(tk, at)
                        if price_c is not None:
                            from app.paper.engine import record_external_close
                            fill = await record_external_close(
                                r["user_id"], r["id"], price_c)
                            if fill.ok:
                                alpaca_reconciled += 1
                                affected_users.add(r["user_id"])
                                out.append(AgentMessage(
                                    agent=self.name, kind="close",
                                    confidence=1.0,
                                    payload={
                                        "user_id": r["user_id"],
                                        "ticker": tk,
                                        "side": r["side"],
                                        "reason": "alpaca_external",
                                        "exit_price": fill.fill_price,
                                        "realized_pnl_usd": fill.realized_pnl_usd,
                                        "position_id": r["id"],
                                        "broker": "alpaca",
                                    }))
                        continue
                    price_c = await _price(tk, at)
                    if price_c is None:
                        alpaca_managed += 1
                        continue
                    stop_c = (float(r["stop_price"])
                              if r.get("stop_price") else None)
                    target_c = (float(r["target_price"])
                                if r.get("target_price") else None)
                    reason_c: str | None = None
                    if r.get("close_requested"):
                        reason_c = "manual"
                    elif r["side"] == "long":
                        if stop_c is not None and price_c <= stop_c:
                            reason_c = "stop"
                        elif target_c is not None and price_c >= target_c:
                            reason_c = "target"
                    else:
                        if stop_c is not None and price_c >= stop_c:
                            reason_c = "stop"
                        elif target_c is not None and price_c <= target_c:
                            reason_c = "target"
                    if reason_c is None:
                        alpaca_managed += 1
                        continue
                    _liq, liq_err = await liquidate_position(
                        tk, asset_type="crypto")
                    if liq_err:
                        # Leave the row open and retry next tick. NEVER
                        # close the Trezo row while Alpaca may still be
                        # holding the coins (Gap 2 lesson).
                        out.append(AgentMessage(
                            agent=self.name, kind="error",
                            payload={
                                "user_id": r["user_id"], "ticker": tk,
                                "error": (
                                    f"crypto {reason_c} exit: Alpaca "
                                    f"liquidate failed: {liq_err}"),
                                "position_id": r["id"],
                                "broker": "alpaca",
                            }))
                        continue
                    fill = await close_position(
                        r["user_id"], r["id"], price_c, reason=reason_c)
                    if fill.ok:
                        affected_users.add(r["user_id"])
                        out.append(AgentMessage(
                            agent=self.name, kind="close", confidence=1.0,
                            payload={
                                "user_id": r["user_id"], "ticker": tk,
                                "side": r["side"], "reason": reason_c,
                                "exit_price": fill.fill_price,
                                "realized_pnl_usd": fill.realized_pnl_usd,
                                "position_id": r["id"],
                                "broker": "alpaca",
                            }))
                    continue
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

                    # Gap 1 fix (2026-06-11, Task #8): intraday time stops
                    # MUST apply to Alpaca-routed rows too. Previously these
                    # rules only ran in the internal-paper branch, so
                    # Alpaca-routed STMS/ORB positions could ride past
                    # their max-hold and 3:45 force-exit windows.
                    if strat_a.startswith("stms") or strat_a.startswith("orb"):
                        price_a = await _price(tk, at)
                        stop_a = float(r["stop_price"]) if r.get("stop_price") else None
                        if price_a is not None:
                            ts_reason, ts_detail = _decide_time_stop(
                                r, r["side"], price_a, stop_a,
                            )
                            if ts_reason:
                                from app.brokers.alpaca import liquidate_position
                                _liq, liq_err = await liquidate_position(tk)
                                out.append(AgentMessage(
                                    agent=self.name, kind="info",
                                    payload={
                                        "user_id": r["user_id"],
                                        "ticker": tk,
                                        "note": (
                                            f"Intraday time stop ({ts_detail}) - "
                                            f"Alpaca position closed at market"
                                            + (f" (error: {liq_err})" if liq_err else "")
                                        ),
                                        "position_id": r["id"],
                                        "broker": "alpaca",
                                        "reason": ts_detail,
                                    }))
                                # Skip the rest for this row; next tick
                                # reconciles the Trezo row once Alpaca
                                # drops it from open positions.
                                continue

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
                        # Naked-position alert (2026-06-11 PM). A day-TIF
                        # bracket's exit legs expire at the close, so a
                        # stock row that survives into the next session
                        # has NO stop and NO target at the broker (live
                        # case: AAPL). Alert-only -- auto-selling here
                        # could double-sell against legs that DO exist.
                        if at == "stock":
                            note = await _naked_position_check(tk, r)
                            if note is not None:
                                out.append(AgentMessage(
                                    agent=self.name, kind="error",
                                    payload=note))
                continue

            # --- Internal paper positions ----------------------------------
            price = await _price(tk, at)
            if price is None:
                continue

            side   = r["side"]
            stop   = float(r["stop_price"]) if r.get("stop_price") else None
            target = float(r["target_price"]) if r.get("target_price") else None
            # Restored 2026-06-11 PM: the morning _decide_time_stop refactor
            # lifted the old `strat = ...` assignment out of this loop but a
            # reference survived at the swing-stop check below -> NameError
            # on EVERY tick that reached an internal row. Position Monitor
            # crash-looped from 10:33 AM ET (found via GET /agents
            # last_error="name 'strat' is not defined").
            strat  = (r.get("strategy") or "").lower()

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
            # Logic lives in _decide_time_stop() so both this branch and
            # the Alpaca branch (Gap 1 fix, Task #8) share the same rules.
            if not close_reason:
                ts_reason, ts_detail = _decide_time_stop(r, side, price, stop)
                if ts_reason:
                    close_reason, close_detail = ts_reason, ts_detail

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
