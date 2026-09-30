"""Per-book entry-only controls. Unknown evidence never becomes permission."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import math
import os

INTRADAY_PREFIXES = ("stms", "orb", "scalp")


def is_intraday(strategy):
    # Shared with the position monitor; crypto time exits remain excluded.
    return str(strategy or "").lower().startswith(INTRADAY_PREFIXES)


def number(value):
    if isinstance(value, bool):
        raise ValueError("boolean is not a number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("nonfinite number")
    return result


def knob(name, default):
    try:
        result = number(os.getenv(name, str(default)))
        return result if result >= 0 else default
    except (ValueError, TypeError):
        return default


def symbol(ticker):
    return str(ticker).upper().replace("/", "")


def reentry_verdict(last, price, lane, side, now, *, cooldown=90, lookback=24, cost=None):
    if last is None:
        return None
    details = {"last_exit_price": last.get("exit_price"), "proposed_entry": price}
    try:
        at = datetime.fromisoformat(str(last["exit_at"]).replace("Z", "+00:00"))
        minutes = (now - at).total_seconds() / 60
        details["minutes_since_exit"] = round(minutes, 2)
        exit_price = number(last["exit_price"])
        if at.tzinfo is None or minutes < 0 or exit_price <= 0 or side not in ("long", "short"):
            raise ValueError("invalid exit evidence")
        if minutes >= lookback * 60:
            return None
        if minutes < cooldown:
            return {**details, "rule": "cooldown"}
        proposed = number(price)
        if proposed <= 0:
            raise ValueError("invalid entry price")
        cost = cost if cost is not None else (0.0062 if lane == "crypto" else 0.0015)
        # The specified band is symmetric for both directions: either a better
        # entry or a breakout beyond round-trip cost. This is not an edge claim.
        if exit_price * (1-cost) < proposed < exit_price * (1+cost):
            return {**details, "rule": "cost_band", "round_trip_cost": cost}
        return None
    except (KeyError, ValueError, TypeError, OverflowError):
        return {**details, "rule": "evidence_unknown"}


async def fresh_entry_price(ticker, lane, side, now):
    from app.brokers import alpaca_data
    crypto = lane == "crypto"
    name = symbol(ticker)
    if crypto:
        name = name[:-3] if name.endswith("USD") else name
    q = await (alpaca_data.get_crypto_quote(name + "/USD") if crypto
               else alpaca_data.get_quote(name))
    if q is None:
        return None
    try:
        if symbol(q.symbol) != (name + "USD" if crypto else name):
            return None
        at = datetime.fromisoformat(str(q.ts).replace("Z", "+00:00"))
        bid, ask = number(q.bid), number(q.ask)
        if not -2 <= (now-at).total_seconds() <= 60 or not 0 < bid <= ask:
            return None
        return ask if side == "long" else bid
    except (ValueError, TypeError, AttributeError):
        return None


async def check_reentry(client, uid, ticker, lane, side, *, held=False, now=None):
    if held or lane not in ("stock", "crypto"):
        return None
    now = now or datetime.now(timezone.utc)
    hours = knob("TREZO_REENTRY_LOOKBACK_H", 24)
    try:
        if client is None:
            raise ValueError("history unavailable")
        names = {str(ticker).upper(), symbol(ticker)}
        if lane == "crypto":
            coin = symbol(ticker).removesuffix("USD")
            names.update((coin, coin+"USD", coin+"/USD"))
        def read():
            return (client.table("paper_positions")
                    .select("exit_at,exit_price,side,status")
                    .eq("user_id", str(uid)).eq("asset_type", lane)
                    .in_("ticker", sorted(names)).like("status", "closed_%")
                    .neq("status", "closed_partial")
                    .gte("exit_at", (now-timedelta(hours=hours)).isoformat())
                    .order("exit_at", desc=True).limit(1).execute())
        rows = (await asyncio.to_thread(read)).data
        if not isinstance(rows, list):
            raise ValueError("history unavailable")
        if not rows:
            return None
        cooldown = knob("TREZO_REENTRY_COOLDOWN_MIN", 90)
        cost = 0.0062 if lane == "crypto" else knob("TREZO_REENTRY_MIN_MOVE_STOCK", 0.0015)
        preliminary = reentry_verdict(rows[0], None, lane, side, now,
                                      cooldown=cooldown, lookback=hours, cost=cost)
        if preliminary and preliminary["rule"] == "cooldown":
            return preliminary
        price = await fresh_entry_price(ticker, lane, side, now)
        return reentry_verdict(rows[0], price, lane, side, now,
                               cooldown=cooldown, lookback=hours, cost=cost)
    except Exception:
        return {"rule": "history_or_quote_unknown"}


def pdt_verdict(snapshot, strategy, lane, *, buffer=2500, minimum=2000):
    if lane != "stock" or not is_intraday(strategy):
        return None
    try:
        equity = number(snapshot["equity"])
        count = number(snapshot["daytrade_count"])
        flagged = snapshot["pattern_day_trader"]
        if (snapshot.get("pdt_state_known") is False or not isinstance(flagged, bool)
                or count < 0 or not count.is_integer()):
            raise ValueError("PDT state unknown")
        details = {"equity": equity, "daytrade_count": int(count), "buffer_usd": buffer}
        if equity < minimum:
            return {**details, "rule": "below_minimum_equity"}
        if equity < 25000 + buffer and (count >= 3 or flagged):
            return {**details, "rule": "day_trade_limit"}
        return None
    except (TypeError, KeyError, ValueError, OverflowError):
        return {"rule": "account_state_unknown"}


def emit(event, uid, ticker, strategy, details):
    try:
        from app.agents.activity_log import record
        record(event, ticker, strategy=str(strategy), reason=str(details.get("rule") or event),
               extra={"user_id": str(uid), **details})
    except Exception:
        pass


async def goal_lock(uid, cfg, strategy, *, client=None):
    if not is_intraday(strategy) or not getattr(cfg, "goal_lock_enabled", True):
        return None
    try:
        from app.paper.daily_goal import goal_state
        from app.runtime.settings import _supabase
        state = await goal_state(uid)
        if state.get("known") is False:
            raise ValueError("goal counters unavailable")
        client = client if client is not None else _supabase()
        if client is None:
            raise ValueError("lock persistence unavailable")
        reply = await asyncio.to_thread(lambda: client.rpc("observe_daily_goal", {
            "p_user_id": str(uid), "p_goal": state["goal"], "p_label": state["label"],
            "p_announce": True}).execute())
        data = reply.data
        if not isinstance(data, dict) or data.get("ok") is not True:
            raise ValueError("goal lock unverified")
        if data["locked"]:
            details = {"rule": "daily_goal_banked", "goal": data["goal"],
                       "label": data["label"], "realized": data["realized_at_lock"],
                       "day": data["day"]}
            if data.get("first_refusal"):
                emit("goal_locked", uid, "BOOK", strategy, details)
            return details
        return None
    except Exception:
        return {"rule": "goal_state_unknown"}
