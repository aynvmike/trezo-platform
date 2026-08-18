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
import os
from datetime import datetime, timezone

from app.config import get_settings
from app.data.candles import fetch_candles_for
import os

from app.paper.engine import close_position, check_and_lock_profit
from app.brokers.accounts import (
    set_account_for_user as _pm_set_account,
    clear_account as _pm_clear_account,
    should_skip_unresolved as _pm_skip_unresolved,
)

# Profit-stepping LADDER (2026-07-02, multi-step per Mike: "it should be
# able to do it multiple times, stepping out over time"). Each step banks
# a fraction of the REMAINING shares when the run to target advances
# another gap: 60%, then 80%, then 100% of the way (defaults; env-
# tunable). Cooldown between steps + a max count stop noise-whittling.
# Restart-proof: on first sight of a position we ask trade_outcomes how
# many steps it already banked (exit_reason='profit_step').
_step_state: dict[str, dict] = {}

# --- SAME-DAY options manager (Mike 2026-07-14) -----------------------
# The options scanner ticks every 30 minutes -- far too slow for a
# 0-DTE round trip. This runs on Position Monitor's 60-second heart:
# +30% is taken the moment it prints, a -25% reversal is sold without
# hoping ("it reverses way too fast to hope of a comeback"), and
# nothing is held past 3:45 PM ET.
_day_opt_last: float = 0.0
_day_opt_done: set = set()
_GAP_DAY = ""   # open-bell gap audit marker (Mike 2026-07-15)
_PRE_BREAK_DAY = ""   # pre-holiday review marker (Mike 2026-07-16)


async def _pre_break_review() -> None:
    """PRE-HOLIDAY REVIEW (Mike 2026-07-16): before every multi-day
    market close, re-evaluate what is held. His rule, encoded: if the
    plan would need a quick sale right after the break without time to
    re-evaluate, sell BEFORE the break -- unless the position is a
    long-term lane. Long-term lanes (hodl/dca/dividend/kindrip/wheel)
    ride; short-horizon stock positions ride ONLY with profit locked
    (stop >= entry); green-but-unprotected ones get their stop raised
    to breakeven (+ broker resync); red ones close into the break.
    Crypto trades 24/7 and is exempt. Every decision logs a
    `preholiday_review` line. Runs once, 2:00-3:45 PM ET on the eve."""
    global _PRE_BREAK_DAY
    from datetime import date as _pb_d
    from datetime import datetime as _pb_dt
    from datetime import timezone as _pb_tz
    now = _pb_dt.now(_pb_tz.utc)
    h = now.hour + now.minute / 60.0
    if not (18.0 <= h <= 19.75):
        return
    today = _pb_d.today().isoformat()
    if _PRE_BREAK_DAY == today:
        return
    try:
        from app.agents.options_scanner import _multi_day_break
        brk = await _multi_day_break()
    except Exception:  # noqa: BLE001
        brk = 0
    _PRE_BREAK_DAY = today
    if brk < 2:
        return
    try:
        import asyncio as _aio
        from app.runtime.settings import _supabase as _sb
        client = _sb()
        if client is None:
            return

        def _q():
            return (client.table("paper_positions")
                    .select("id, ticker, user_id, side, quantity, "
                            "entry_price, stop_price, target_price, "
                            "asset_type, broker, strategy")
                    .eq("status", "open").execute())
        rows = (await _aio.to_thread(_q)).data or []
        from app.agents.activity_log import record as _rec
        LONG_TERM = ("hodl", "dca", "dividend", "kindrip", "wheel")
        for r in rows[:20]:
            try:
                tk = str(r.get("ticker") or "")
                uid = str(r.get("user_id") or "")
                strat = str(r.get("strategy") or "").lower()
                if str(r.get("asset_type") or "stock") == "crypto":
                    continue      # 24/7 market -- no closed-day gap risk
                if any(k in strat for k in LONG_TERM):
                    _rec("preholiday_review", tk,
                         reason=(f"market closed {brk} day(s) next -- "
                                 f"long-term lane ({strat}) rides the "
                                 f"break by design"),
                         extra={"user_id": uid})
                    continue
                entry = float(r.get("entry_price") or 0)
                stop = float(r.get("stop_price") or 0)
                cnd = await fetch_candles_for(tk, "stock")
                px = float(cnd[-1].close) if cnd else 0.0
                if px <= 0 or entry <= 0:
                    continue
                if stop >= entry:
                    _rec("preholiday_review", tk,
                         reason=(f"rides the {brk}-day break with profit "
                                 f"locked (stop {stop:.2f} >= entry "
                                 f"{entry:.2f}) -- a gap cannot turn it "
                                 f"into a loss"),
                         extra={"user_id": uid})
                elif px > entry:
                    def _upd(rid=r["id"], ns=round(entry, 4)):
                        return (client.table("paper_positions")
                                .update({"stop_price": ns})
                                .eq("id", rid).execute())
                    await _aio.to_thread(_upd)
                    r["stop_price"] = round(entry, 4)
                    try:
                        if str(r.get("broker") or "") == "alpaca":
                            from app.paper.leg_sync import (
                                resync_alpaca_legs,
                            )
                            await resync_alpaca_legs(
                                r, why="pre-break: stop raised to breakeven")
                    except Exception:  # noqa: BLE001
                        pass
                    _rec("preholiday_review", tk,
                         reason=(f"green but unprotected into a {brk}-day "
                                 f"break -- stop raised to breakeven "
                                 f"({entry:.2f})"),
                         extra={"user_id": uid})
                else:
                    def _cls(rid=r["id"]):
                        return (client.table("paper_positions")
                                .update({"close_requested": True})
                                .eq("id", rid).execute())
                    await _aio.to_thread(_cls)
                    _rec("preholiday_review", tk,
                         reason=(f"red short-horizon position into a "
                                 f"{brk}-day break -- selling before the "
                                 f"close: no time to re-evaluate right "
                                 f"after (Mike's rule)"),
                         extra={"user_id": uid})
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        pass


async def _gap_check_open_bell() -> None:
    """Open-bell GAP AUDIT (Mike 2026-07-15: "when the price gaps up or
    down we need a way to make sure the agents deal with it"). Runs once
    per day in the first half hour: every held stock is checked against
    yesterday's close. Gap DOWN >= 3% that has NOT breached the stop ->
    tighten the stop to ~2% under the open and push it to the broker
    (cap further bleed). Gap UP -> the trail ratchets the lock and the
    TP limit fills at the better price; we log the read either way so
    the audit trail shows the gap was SEEN and handled."""
    global _GAP_DAY
    from datetime import date as _g_d
    from datetime import datetime as _g_dt
    from datetime import timezone as _g_tz
    now = _g_dt.now(_g_tz.utc)
    h = now.hour + now.minute / 60.0
    if not (13.5 <= h <= 14.2):
        return
    today = _g_d.today().isoformat()
    if _GAP_DAY == today:
        return
    _GAP_DAY = today
    try:
        import asyncio as _aio
        import os as _go
        from app.runtime.settings import _supabase as _sb
        client = _sb()
        if client is None:
            return

        def _q():
            return (client.table("paper_positions")
                    .select("id, ticker, user_id, side, quantity, "
                            "entry_price, stop_price, target_price, "
                            "asset_type, broker")
                    .eq("status", "open").eq("asset_type", "stock")
                    .execute())
        rows = (await _aio.to_thread(_q)).data or []
        thr = float(_go.getenv("TREZO_GAP_ALERT_PCT", "0.03"))
        from app.agents.activity_log import record as _grec
        for r in rows[:12]:
            try:
                cnd = await fetch_candles_for(str(r["ticker"]), "stock")
                if not cnd or len(cnd) < 2:
                    continue
                prev = float(cnd[-2].close)
                cur = float(cnd[-1].close)
                if prev <= 0 or cur <= 0:
                    continue
                gap = cur / prev - 1.0
                if abs(gap) < thr:
                    continue
                uid = str(r.get("user_id") or "")
                if gap <= -thr and str(r.get("side") or "long") == "long":
                    stop = float(r.get("stop_price") or 0)
                    new_s = round(cur * 0.98, 4)
                    if stop and cur > stop and new_s > stop:
                        def _upd(rid=r["id"], ns=new_s):
                            return (client.table("paper_positions")
                                    .update({"stop_price": ns})
                                    .eq("id", rid).execute())
                        await _aio.to_thread(_upd)
                        r["stop_price"] = new_s
                        try:
                            if str(r.get("broker") or "") == "alpaca":
                                from app.paper.leg_sync import (
                                    resync_alpaca_legs,
                                )
                                await resync_alpaca_legs(
                                    r, why=(f"gap-down {gap * 100:.1f}% at "
                                            f"the open -- stop tightened"))
                        except Exception:  # noqa: BLE001
                            pass
                        _grec("gap_check", str(r["ticker"]),
                              reason=(f"gapped DOWN {gap * 100:.1f}% at the "
                                      f"open -- stop tightened to "
                                      f"{new_s:.2f} to cap further bleed"),
                              extra={"user_id": uid})
                    else:
                        _grec("gap_check", str(r["ticker"]),
                              reason=(f"gapped DOWN {gap * 100:.1f}% at the "
                                      f"open -- existing stop stands; the "
                                      f"broker fills at market if touched"),
                              extra={"user_id": uid})
                elif gap >= thr:
                    _grec("gap_check", str(r["ticker"]),
                          reason=(f"gapped UP {gap * 100:.1f}% at the open "
                                  f"-- trail ratchets the lock; the TP "
                                  f"limit fills at the better price"),
                          extra={"user_id": uid})
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        pass


async def _manage_day_options() -> None:
    global _day_opt_last
    import os as _os2
    import time as _t2
    if (_t2.time() - _day_opt_last) < 55.0:
        return
    _day_opt_last = _t2.time()
    try:
        from app.runtime.settings import _supabase as _sb
        client = _sb()
        if client is None:
            return
        import asyncio as _aio

        def _q():
            return (client.table("options_positions")
                    .select("id, user_id, underlying, option_type, strike, "
                            "contracts, net_premium_usd, expiration")
                    .eq("status", "open").eq("strategy", "option_day")
                    .limit(4).execute())
        rows = (await _aio.to_thread(_q)).data or []
        if not rows:
            return
        from datetime import datetime as _dt2
        from datetime import timezone as _tz2
        _now = _dt2.now(_tz2.utc)
        _h = _now.hour + _now.minute / 60.0
        _force = _h >= 19.75      # 3:45 PM EDT (safely early in EST too)
        _tp = 1.0 + float(_os2.getenv("TREZO_DAY_OPT_TP", "0.30"))
        _cut = 1.0 - float(_os2.getenv("TREZO_DAY_OPT_CUT", "0.25"))
        for r in rows:
            rid = str(r.get("id"))
            if rid in _day_opt_done:
                continue
            u = str(r.get("underlying") or "").upper()
            strike = float(r.get("strike") or 0)
            ct = int(r.get("contracts") or 1)
            otype = str(r.get("option_type") or "call").lower()
            exp = str(r.get("expiration") or "")
            entry = (abs(float(r.get("net_premium_usd") or 0))
                     / (100.0 * max(ct, 1)))
            if not u or strike <= 0 or len(exp) < 10 or entry <= 0:
                continue
            occ = (f"{u}{exp[2:4]}{exp[5:7]}{exp[8:10]}"
                   f"{'C' if otype.startswith('c') else 'P'}"
                   f"{int(round(strike * 1000)):08d}")
            from app.brokers.alpaca_data import get_option_quote
            prem = await get_option_quote(occ)
            if not prem or prem <= 0:
                if not _force:
                    continue
                prem = entry          # force-close blind if the quote is gone
            ratio = float(prem) / entry
            why = None
            if ratio >= _tp:
                why = (f"+{(_tp - 1) * 100:.0f}% fast take -- "
                       f"banked the quick move")
            elif ratio <= _cut:
                why = (f"-{(1 - _cut) * 100:.0f}% reversal cut -- it "
                       f"reverses too fast to hope for a comeback")
            elif _force:
                why = "3:45 ET force-close -- same-day trades never sleep over"
            if not why:
                continue
            _day_opt_done.add(rid)
            from app.brokers.alpaca import submit_option_order
            _o, _e = await submit_option_order(
                occ, ct, "sell", time_in_force="day",
                limit_price=round(max(0.01, float(prem)) * 0.95, 2))
            try:
                from app.agents.activity_log import record as _rec2
                _rec2("option_day_exit", u, strategy="option_day",
                      reason=((f"selling {ct} {otype.upper()} {strike:g} at "
                               f"~{float(prem):.2f} ({ratio:.2f}x entry) -- "
                               f"{why}")
                              if not _e else
                              f"same-day exit order failed: {str(_e)[:90]}"),
                      extra={"user_id": str(r.get("user_id"))})
            except Exception:  # noqa: BLE001
                pass
            if _e:
                _day_opt_done.discard(rid)   # retry on the next pass
    except Exception:  # noqa: BLE001
        pass


def _step_profile(notional: float) -> tuple[float, float]:
    """(first-step trigger, bank fraction) for one position. BIG positions
    (Mike 2026-07-08: "take 5% and be able to make another trade -- two
    quick wins beat locking $1k on a 10% probability") step EARLIER (40%
    of the run) and bank BIGGER (60%), so the capital recycles into the
    next setup instead of waiting on the full move."""
    try:
        big = float(os.getenv("TREZO_BIG_TRADE_USD", "900"))
        if notional >= big:
            return (float(os.getenv("TREZO_BIG_TRADE_STEP_AT", "0.4")),
                    min(0.9, max(0.1, float(os.getenv(
                        "TREZO_BIG_TRADE_STEP_FRACTION", "0.6")))))
    except Exception:  # noqa: BLE001
        pass
    return (float(os.getenv("TREZO_PROFIT_STEP_AT", "0.6")),
            min(0.9, max(0.1, float(os.getenv(
                "TREZO_PROFIT_STEP_FRACTION", "0.5")))))


def _step_params() -> tuple[float, float, int, float]:
    def _f(name, d):
        try:
            return float(os.getenv(name, str(d)))
        except (TypeError, ValueError):
            return d
    return (_f("TREZO_PROFIT_STEP_AT", 0.6),
            _f("TREZO_PROFIT_STEP_GAP", 0.2),
            int(_f("TREZO_PROFIT_STEP_MAX", 3)),
            _f("TREZO_PROFIT_STEP_COOLDOWN_S", 900.0))


async def _step_check(pid: str, user_id, run: float,
                      at0_override: float | None = None) -> tuple[bool, int]:
    """Should the NEXT step fire at this run-progress? -> (fire, steps_so_far)."""
    import time as _t
    at0, gap, max_n, cool = _step_params()
    if at0_override is not None:
        at0 = float(at0_override)
    # Daily-goal nudge (Mike 2026-07-13): if the day's paycheck is still
    # short after 2 PM ET, take the first bank a touch EARLIER (85% of the
    # usual trigger). Never later, never bigger risk -- the goal only ever
    # tightens behavior.
    try:
        from datetime import datetime as _dgt
        from datetime import timezone as _dgz
        if 18 <= _dgt.now(_dgz.utc).hour <= 21:
            from app.paper.daily_goal import goal_state as _dgs
            _g = await _dgs(user_id)
            if not _g.get("hit"):
                at0 = at0 * 0.85
    except Exception:  # noqa: BLE001
        pass
    st = _step_state.get(pid)
    if st is None:
        n0 = 0
        try:
            from app.paper.engine import count_profit_steps
            n0 = await count_profit_steps(str(user_id), pid)
        except Exception:  # noqa: BLE001
            n0 = 0
        st = {"n": int(n0), "ts": 0.0}
        _step_state[pid] = st
    if st["n"] >= max_n:
        return False, st["n"]
    if (_t.time() - st["ts"]) < cool:
        return False, st["n"]
    need = at0 + gap * st["n"]
    return (run >= need), st["n"]


def _step_mark(pid: str) -> None:
    import time as _t
    st = _step_state.setdefault(pid, {"n": 0, "ts": 0.0})
    st["n"] += 1
    st["ts"] = _t.time()
from app.strategies.extended import SWING_MAX_HOLD_DAYS
from app.agents.reevaluator import reeval_is_enabled, reevaluate_position

from .base import Agent, AgentMessage
from app.runtime.asset_policy import policy_for as _asset_policy
from app.runtime.asset_policy import trail_policy_for as _trail_policy

# Day-trade management thresholds (Phase 8e).
MAX_HOLD_MINUTES = 90
STAGNATION_MINUTES = 75
STAGNATION_R = 0.25

# Stock profit trail-to-lock (Mike 2026-06-23: catch profit drawdown on
# HELD stocks, not just at entry). Once a long stock is >= MIN_GAIN above
# entry, ratchet its stop UP to lock (1 - GIVEBACK) of the gain; it sells
# on a giveback. The trailed stop sits below the current price and never
# below entry -> can only protect a winner, never forces a loss, never an
# instant sell on activation. Default ON; env-tunable.
STOCK_TRAIL_ENABLED = os.getenv("TREZO_STOCK_PROFIT_TRAIL", "1").strip().lower() not in ("0", "false", "no", "off")
STOCK_TRAIL_MIN_GAIN = float(os.getenv("TREZO_STOCK_TRAIL_MIN_GAIN", "0.03"))
# Scalps arm their trail EARLIER than swings (2026-08-07). Retiring the
# +0.63% net-edge exit left a scalp with no way out between +0.63% and its
# +3% target, because the shared trail also armed at 3%. Positions simply
# sat: closes fell 20 -> 7 -> 2 per day over three days while ETH, LINK,
# DOT and SOL stayed stuck, and anti-stacking then blocked every new entry
# in those names until approvals hit zero. Arming at 2% locks no lower
# than 1.40% after a 30% giveback -- 2.3x round-trip cost, so it is a real
# profit rather than the pennies the old rule took.
SCALP_TRAIL_MIN_GAIN = float(os.getenv("TREZO_SCALP_TRAIL_MIN_GAIN", "0.02"))
STOCK_TRAIL_GIVEBACK = float(os.getenv("TREZO_STOCK_TRAIL_GIVEBACK", "0.30"))


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
    # DELIBERATE, NOT A GAP (Mike, 2026-08-05, asked directly): crypto is
    # excluded from every time-based exit on purpose. "I did not want to
    # include that because of the possibility of the reach of profit."
    #
    # crypto_* strategies do not match these prefixes, so no crypto trade
    # is ever closed by max_hold_90min or the 75-minute stagnation rule.
    # That is the intent, not an oversight of the naming: crypto trades
    # 24/7, and a 90-minute cap would close positions long before they
    # could reach the +3% that arms the trailing stop. At 60% annual
    # volatility a +3% move inside 90 minutes is roughly a 4-sigma event.
    #
    # DO NOT "fix" this by adding a crypto_ prefix here. Changing it is a
    # trading decision that belongs to Mike, not a bug fix.
    if not (strat.startswith("stms") or strat.startswith("orb")
            or strat.startswith("scalp")):
        return None, ""

    now = datetime.now(timezone.utc)
    held = _minutes_since(r.get("entry_at"))

    # 2026-07-08 (Mike): STMS trades all day now -- the 11 AM force-stop
    # is retired; the generic intraday rules below still govern it.
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


async def _maybe_trail_hodl(r: dict, price: float) -> float | None:
    """HODL trail-to-lock (crypto Part 2, 2026-06-13). For a long HODL row
    that has run >= HODL_TRAIL_TRIGGER in profit, RAISE (never lower) its
    stop to lock gains -- without ever setting a profit target, so the
    position still holds. Returns the new stop if it ratcheted up (and
    persists it to the row), else None. Long-only."""
    from app.strategies.crypto import HODL_TRAIL_TRIGGER, HODL_TRAIL_GIVEBACK
    from app.runtime.capabilities import trailing_stop_from_price
    try:
        entry = float(r.get("entry_price") or 0)
    except (TypeError, ValueError):
        return None
    if entry <= 0 or price <= 0:
        return None
    new_stop = trailing_stop_from_price(
        price, "long", HODL_TRAIL_GIVEBACK, entry=entry, trigger_gain=HODL_TRAIL_TRIGGER)
    if new_stop is None:
        return None
    try:
        cur = float(r["stop_price"]) if r.get("stop_price") else None
    except (TypeError, ValueError):
        cur = None
    if cur is not None and new_stop <= cur:
        return None  # only ever ratchet UP
    client = _supabase()
    if client is None:
        return None
    rid = r.get("id")

    def _upd():
        return (client.table("paper_positions")
                .update({"stop_price": new_stop}).eq("id", rid).execute())

    try:
        await asyncio.to_thread(_upd)
    except Exception:  # noqa: BLE001
        return None
    r["stop_price"] = new_stop
    await _push_stop_to_broker(r, new_stop)
    return new_stop


async def _push_stop_to_broker(r: dict, new_stop: float) -> None:
    """Mirror a ratcheted stop to the VENUE, where it keeps working when
    we do not.

    Until 2026-08-18 every trailing stop in Trezo lived only in our
    ledger, enforced by the monitor watching the tape. That is fine right
    up to the moment the monitor stops watching -- and on 8/17 it stopped
    for fifteen hours while three books held positions. A stop resting at
    the broker survives a crash, a restart, a locked-out afternoon and a
    deleted instance.

    Only for venues that actually hold stops: the asset policy decides,
    so crypto (no native stop at Alpaca) is skipped rather than failing
    noisily every tick. Ratchet-only, and never raises -- a failure here
    must not stop the ledger-side protection that already worked."""
    if os.getenv("TREZO_BROKER_STOP_SYNC", "1") == "0":
        return
    if str(r.get("broker") or "") != "alpaca":
        return
    try:
        if not _asset_policy(r.get("asset_type")).native_brackets:
            return          # e.g. crypto: the venue cannot hold a stop
        from app.brokers.alpaca import ratchet_stop
        changed, note = await ratchet_stop(
            str(r.get("ticker") or ""), float(new_stop),
            qty=float(r.get("quantity") or 0) or None,
            target_price=(float(r["target_price"])
                          if r.get("target_price") else None))
        if changed:
            from app.agents.activity_log import record
            record("broker_stop_moved", str(r.get("ticker") or "?"),
                   strategy=str(r.get("strategy") or ""), reason=note,
                   extra={"user_id": str(r.get("user_id") or "")})
    except Exception:  # noqa: BLE001
        pass


async def _maybe_ladder_stop(r: dict, price: float, ladder) -> float | None:
    """Step-ladder profit lock (crypto Part 2b, 2026-06-13). For a long
    position, as unrealized gain (return on capital) climbs through the
    ladder's tiers, ratchet the stop UP to that tier's locked floor --
    locking gains in stages while the trade still rides to its target.
    ``ladder`` = ((gain_trigger, locked_floor), ...) as fractions of entry.
    Returns the new stop if it ratcheted up (and persists it), else None.
    Never lowers a stop. Long-only."""
    from app.runtime.capabilities import ladder_stop
    new_stop = ladder_stop(r.get("entry_price"), price, ladder, "long")
    if new_stop is None:
        return None  # below the first rung / bad input -> keep original stop
    try:
        cur = float(r["stop_price"]) if r.get("stop_price") else None
    except (TypeError, ValueError):
        cur = None
    if cur is not None and new_stop <= cur:
        return None  # only ever ratchet UP
    client = _supabase()
    if client is None:
        return None
    rid = r.get("id")

    def _upd():
        return (client.table("paper_positions")
                .update({"stop_price": new_stop}).eq("id", rid).execute())

    try:
        await asyncio.to_thread(_upd)
    except Exception:  # noqa: BLE001
        return None
    r["stop_price"] = new_stop
    await _push_stop_to_broker(r, new_stop)
    return new_stop


async def _maybe_trail_stock_profit(r: dict, price: float,
                                    min_gain: float | None = None) -> float | None:
    """Stock profit trail-to-lock (Mike 2026-06-23). For a LONG stock up
    >= STOCK_TRAIL_MIN_GAIN over entry, RAISE (never lower) the stop to lock
    in (1 - STOCK_TRAIL_GIVEBACK) of the current gain. As price climbs the
    stop ratchets up; when price gives back to it the normal stop-check sells,
    locking the profit. The new stop is always below the current price and
    never below entry -- so it can only protect a winner, never force a loss,
    and never sells the instant it engages. Persists the stop. Long-only."""
    from app.runtime.capabilities import trailing_profit_stop
    side = str(r.get("side") or "").lower()
    try:
        entry = float(r.get("entry_price") or 0)
    except (TypeError, ValueError):
        return None
    # TRAIL FROM THE PEAK, NOT THE LAST TICK (Mike 2026-07-27: "it held
    # the ETH trade too long... it was a winning trade").
    # Post-mortem, ETH 7/13-7/17: entry $1,772.06, peak $1,940.59
    # (+$67.47), exited on the trail at $1,856.36 for +$33.75 -- HALF the
    # peak gain surrendered on a winner. Cause: this trail measured the
    # gain from the price the monitor happened to observe on a 60s tick,
    # so a peak that printed between ticks was never priced in. The row
    # ALREADY stores peak_price; it just was not being used here. Trail
    # from max(peak_price, price) so the lock reflects the best the trade
    # actually reached. On that ETH trade the stop would have sat at
    # $1,890.03 = +$47.23 instead of +$33.75.
    _anchor = price
    try:
        _pk = float(r.get("peak_price") or 0)
        if _pk > 0:
            _anchor = max(price, _pk) if side == "long" else min(price, _pk)
    except (TypeError, ValueError):
        _anchor = price
    _arm = STOCK_TRAIL_MIN_GAIN if min_gain is None else float(min_gain)
    new_stop = trailing_profit_stop(entry, _anchor, side, _arm, STOCK_TRAIL_GIVEBACK)
    # A peak-anchored stop cannot be WRITTEN above the live price for a
    # long (below for a short) -- the broker would reject it and a
    # modeled row would fire instantly. But that case is exactly the one
    # Mike cares about: the giveback ALREADY happened between ticks, and
    # the doctrine is "the profit lock is the key". So instead of
    # silently holding, tuck the stop just under the live price and let
    # the normal stop-check bank it on the next pass -- every exit still
    # flows through the tested liquidation path.
    if new_stop is not None:
        _edge = float(os.getenv("TREZO_TRAIL_BANK_EDGE", "0.0015"))
        if side == "long" and new_stop >= price:
            _bank = round(price * (1.0 - _edge), 4)
            new_stop = _bank if _bank > entry else None
        elif side == "short" and new_stop <= price:
            _bank = round(price * (1.0 + _edge), 4)
            new_stop = _bank if (_bank < entry and entry > 0) else None
    if new_stop is None:
        return None
    try:
        cur = float(r["stop_price"]) if r.get("stop_price") else None
    except (TypeError, ValueError):
        cur = None
    if cur is not None:
        if side == "long" and new_stop <= cur:
            return None  # long: ratchet UP only
        if side == "short" and new_stop >= cur:
            return None  # short: ratchet DOWN only (tighter)
    client = _supabase()
    if client is None:
        return None
    rid = r.get("id")

    def _upd():
        return (client.table("paper_positions")
                .update({"stop_price": new_stop}).eq("id", rid).execute())

    try:
        await asyncio.to_thread(_upd)
    except Exception:  # noqa: BLE001
        return None
    r["stop_price"] = new_stop
    await _push_stop_to_broker(r, new_stop)
    # Broker-held rows: the ratchet must move the REAL stop leg too
    # (Mike 2026-07-14: a DB-only trail protects nothing at Alpaca).
    try:
        if str(r.get("broker") or "") == "alpaca":
            from app.paper.leg_sync import resync_alpaca_legs
            await resync_alpaca_legs(
                r, why=f"profit trail ratcheted the stop to {new_stop:.2f}")
    except Exception:  # noqa: BLE001
        pass
    return new_stop


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


# --- Liquidation throttle / circuit-breaker (Mike 2026-06-15) ----------------
# The exit branches below call liquidate_position every tick while a position
# sits past its stop. If the broker keeps REJECTING/CANCELING the close (e.g. a
# day-TIF bracket conflict -- the GM 6/13 canceled-sell storm), an un-throttled
# retry fires a market order every ~60s: order spam + repeated rejects that trip
# the session kill-switch. This wrapper rate-limits attempts per symbol and
# trips a circuit-breaker after repeated failures so the bot backs off + alerts
# ONCE instead of hammering forever.
_liq_attempt_at: dict[str, float] = {}
_liq_fail_count: dict[str, int] = {}
_LIQ_COOLDOWN_S = 120   # at most one close attempt per symbol per 2 min
_LIQ_MAX_FAILS = 3      # after 3 consecutive failures, back off (alert once)


async def _alpaca_profit_step(r, price: float,
                              frac: float | None = None) -> tuple[bool, str]:
    """Bank a slice of a broker-held LONG winner, then re-protect the
    remainder. VERIFIED at each step; on failure it restores protection
    and reports. (Mike 2026-07-02: partial selling controls drawdown --
    but a botched leg dance leaves shares naked, so nothing proceeds
    unverified.) Returns (stepped, note).

    Any asset class the registry allows to step: the policy decides the
    slice size, whether there are bracket legs to renegotiate first, and
    whether the venue is even open. It was stocks-only until 2026-08-17,
    which is why crypto banked nothing for six weeks."""
    from app.brokers.alpaca import (
        cancel_open_orders_for, get_open_orders_for,
        submit_market_sell, submit_oco_sell,
    )
    from app.runtime.asset_policy import policy_for
    sym = str(r.get("ticker") or "").upper()
    pol = policy_for(r.get("asset_type"))
    # 2026-08-17: this used to be stocks-only by omission, not by
    # decision -- the caller gated on `at == "stock"` and crypto could
    # never bank a slice however far it ran. The asset policy now says
    # who may step, how small a slice may be, and whether the venue
    # holds a bracket we have to renegotiate first.
    if not pol.supports_partial_step:
        return False, f"{pol.label} does not step out by policy"
    try:
        qty_total = float(r.get("quantity") or 0)
        entry = float(r.get("entry_price") or 0)
        stop_p = float(r.get("stop_price") or 0)
        target_p = float(r.get("target_price") or 0)
    except (TypeError, ValueError):
        return False, "bad row numbers"
    if entry <= 0 or target_p <= entry:
        return False, "row lacks a usable target"
    # A broker-held bracket must be re-placed after the slice, so it needs
    # a stop to re-place. Where the venue holds no bracket at all (Alpaca
    # crypto) there is nothing to renegotiate, and a missing stop must not
    # block banking a winner.
    if pol.native_brackets and stop_p <= 0:
        return False, "row lacks usable stop/target"
    if frac is None:
        frac = min(0.9, max(0.1, float(
            os.getenv("TREZO_PROFIT_STEP_FRACTION", "0.5"))))
    slice_qty = pol.slice_size(qty_total, frac)
    if slice_qty <= 0:
        return False, "too small to split"
    remaining = qty_total - slice_qty
    # 0) SESSION GATE (2026-08-05). Equity bracket legs cannot be
    #    cancelled while the market is shut, so every overnight attempt
    #    failed at step 1 and retried forever: 47 identical aborts on
    #    PYPL at 03:00 ET in a single night, 78% of every abort ever
    #    logged. The profit was never taken because the harvest kept
    #    running when it could not possibly succeed. Crypto is exempt --
    #    it genuinely trades 24/7.
    if pol.session_gated:
        try:
            from app.agents.ops_watchdog import _us_market_open
            if not _us_market_open():
                return False, "market closed - step harvest deferred to the open"
        except Exception:  # noqa: BLE001
            pass
    # 1) Release the units: cancel bracket legs (cancel-legs-first, 6/12
    #    lesson) and VERIFY they are gone before selling anything. Skipped
    #    where the venue holds no bracket -- there are no legs to cancel,
    #    and asking would only invent a failure mode.
    if pol.native_brackets:
        _n, err = await cancel_open_orders_for(sym)
        if err:
            return False, f"could not list legs ({err}) - aborted untouched"
        left = None
        for _ in range(4):
            left = await get_open_orders_for(sym)
            if left == []:
                break
            await asyncio.sleep(0.7)
    else:
        left = []
    # get_open_orders_for returns None when the CALL ITSELF failed, and
    # [] only when the broker confirmed there is nothing open. `if left:`
    # treated None as falsy, so a failed check read as "all clear" and
    # the sell proceeded without ever verifying the legs were gone --
    # the exact naked-shares outcome the 6/12 cancel-legs-first rule
    # exists to prevent. An unverifiable check must abort, not assume.
    if left is None:
        return False, "could not verify legs were cancelled - aborted untouched"
    if left:
        return False, "legs did not cancel - aborted untouched"
    # 2) Sell the slice at market, through the venue's own order shape.
    #    Crypto is a different endpoint and a different time-in-force
    #    ('day' is rejected on a 24/7 venue), so the asset policy picks.
    if pol.asset_type == "crypto":
        from app.brokers.alpaca import submit_crypto_order
        order, serr = await submit_crypto_order(sym, "sell", slice_qty)
    else:
        order, serr = await submit_market_sell(sym, slice_qty)
    if serr or not order:
        # Nothing sold -- put the FULL protection back before leaving.
        if pol.native_brackets:
            await submit_oco_sell(sym, qty_total, target_p, stop_p)
            return False, f"slice sell rejected ({serr}); protection restored"
        return False, f"slice sell rejected ({serr}); position untouched"
    # 3) Re-protect the remainder (OCO: original target + stop), retry once.
    #    Where the venue holds no bracket, protection was never AT the
    #    broker: the monitor enforces this row's stop client-side every
    #    tick, so the remainder is as protected as it ever was.
    if not pol.native_brackets:
        protected = True
    else:
        prot, perr = await submit_oco_sell(sym, remaining, target_p, stop_p)
        if perr or not prot:
            await asyncio.sleep(1.0)
            prot, perr = await submit_oco_sell(sym, remaining, target_p, stop_p)
        protected = bool(prot) and not perr
    # 4) Book the slice (closed_partial row + reduced open row).
    from app.paper.engine import record_external_partial_close
    fill = await record_external_partial_close(
        r["user_id"], r["id"], slice_qty, price)
    # 2026-08-17: this said the bare words "booking failed" on every
    # single step for six weeks -- the slice really sold at the broker,
    # the ledger insert was rejected by a status CHECK constraint, and
    # the reason was thrown away right here. An error we swallow is an
    # error nobody fixes. Say what the database said.
    if fill.ok:
        booked = f"${fill.realized_pnl_usd:+.2f}"
    else:
        booked = f"BOOKING FAILED: {str(fill.error or 'unknown')[:120]}"
    _unit = "units" if pol.fractional else "shares"
    _fmt = (f"{slice_qty:g}/{qty_total:g}" if pol.fractional
            else f"{int(slice_qty)}/{int(qty_total)}")
    note = (f"banked {_fmt} {_unit} ({booked}); "
            + ("remainder re-protected (OCO)" if protected
               else "remainder NOT re-protected - naked-guard enforcing"))
    return True, note


async def _throttled_liquidate(symbol: str, asset_type: str = "stock"):
    """Rate-limited + circuit-broken wrapper around liquidate_position.
    Returns (result, status): 'ok' submitted; 'error:<msg>' broker ran but
    failed; 'throttled' skipped (within cooldown); 'circuit_open' skipped (too
    many consecutive fails). Never raises."""
    import time as _t
    now_s = _t.time()
    if _liq_fail_count.get(symbol, 0) >= _LIQ_MAX_FAILS:
        return None, "circuit_open"
    if now_s - _liq_attempt_at.get(symbol, 0.0) < _LIQ_COOLDOWN_S:
        return None, "throttled"
    _liq_attempt_at[symbol] = now_s
    try:
        from app.brokers.alpaca import liquidate_position
        _res, _err = await liquidate_position(symbol, asset_type=asset_type)
    except Exception as e:  # noqa: BLE001
        _liq_fail_count[symbol] = _liq_fail_count.get(symbol, 0) + 1
        return None, "error:" + str(e)[:120]
    if _err:
        _liq_fail_count[symbol] = _liq_fail_count.get(symbol, 0) + 1
        try:
            from app.agents.activity_log import record as _arec
            _arec("exit_error", symbol, reason=str(_err)[:180],
                  extra={"asset_type": asset_type})
        except Exception:  # noqa: BLE001
            pass
        return None, "error:" + str(_err)
    _liq_fail_count[symbol] = 0
    try:
        from app.agents.activity_log import record as _arec
        _arec("exit_liquidate", symbol, reason="liquidation submitted",
              extra={"asset_type": asset_type})
    except Exception:  # noqa: BLE001
        pass
    return _res, "ok"


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
        # Same-day options ride a 60-second leash (Mike 2026-07-14).
        try:
            await _manage_day_options()
        except Exception:  # noqa: BLE001
            pass
        # Open-bell gap audit (Mike 2026-07-15) -- once per day.
        try:
            await _gap_check_open_bell()
        except Exception:  # noqa: BLE001
            pass
        # Pre-holiday position review (Mike 2026-07-16) -- break's eve.
        try:
            await _pre_break_review()
        except Exception:  # noqa: BLE001
            pass
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
                from app.paper.stocks_reconcile import (
                    reconcile_stocks_all_users,
                    reconcile_account_balances_all_users,
                )
                result = await reconcile_stocks_all_users()
                # 2026-06-16: keep the cash ledger synced to broker truth on
                # the same cadence (best-effort; never blocks the tick).
                try:
                    await reconcile_account_balances_all_users()
                except Exception:  # noqa: BLE001
                    pass
                # Adopt anything the broker holds that we have no row for
                # (2026-08-17). The reconcile above only fixes rows we
                # already have; a position with no row is a position the
                # ladder, the stop and the target never see. On crypto,
                # where Alpaca holds no bracket, it is also a position
                # with no stop anywhere. Best-effort, never blocks a tick.
                try:
                    if os.getenv("TREZO_ADOPT_ORPHANS", "1") != "0":
                        from app.paper.adoption import adopt_all_books
                        _adopt = await adopt_all_books(
                            dry_run=os.getenv("TREZO_ADOPT_DRY_RUN", "0") == "1")
                        if _adopt.get("adopted"):
                            result = dict(result or {})
                            result["adopted"] = _adopt.get("adopted")
                except Exception:  # noqa: BLE001
                    pass
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

        # Phase 8g: which symbols the broker still holds. None = could not
        # check (so a transient failure never closes a position by mistake).
        #
        # 2026-08-17: this was ONE call, made HERE -- fifty lines BEFORE
        # the per-row account binding below. So the answer was always the
        # first-bound (primary) account's holdings, and every 25k/75k row
        # whose symbol the primary did not also hold failed the membership
        # test and was closed as a phantom. Nine real positions per book
        # went unmanaged, and because Alpaca holds no bracket on crypto,
        # those coins had no stop at all.
        #
        # It is now asked PER BOOK, inside the loop, through book_scope --
        # which binds the book as part of answering, so the wrong order is
        # no longer expressible. Cleared each tick: a stale holdings set is
        # precisely the input that phantom-closes a live position.
        from app.runtime import book_scope
        book_scope.new_cycle()
        alpaca_held = None

        async def _price(tk: str, at: str) -> float | None:
            key = f"{tk}:{at}"
            if key not in price_cache:
                p = await _latest_price(tk, at)
                if p is not None:
                    price_cache[key] = p
            return price_cache.get(key)

        for r in rows:
            # Bind THIS row's book before any broker action. Exits are
            # routed per position, and an exit for one book executed on
            # another would close the wrong position AND leave the right
            # one open. Set inline rather than `with`: the body is ~500
            # lines and re-indenting live exit code is the riskier edit.
            if _pm_skip_unresolved(str(r.get("user_id") or "")):
                continue          # unknown book: never act on the primary
            _pm_set_account(str(r.get("user_id") or ""))
            # Route guard (8/11): an exit on the wrong account would close
            # a stranger's position AND leave the real one open. Verify the
            # binding actually took before any broker action on this row.
            try:
                from app.brokers.route_guard import (
                    check_route as _pm_check, record_mismatch as _pm_mm)
                _rok, _rnote = _pm_check(str(r.get("user_id") or ""))
                if not _rok:
                    _pm_mm(str(r.get("ticker") or "?"),
                           str(r.get("user_id") or ""), _rnote, "monitor")
                    continue
            except Exception:  # noqa: BLE001
                pass
            tk = r["ticker"]
            at = r["asset_type"]
            # Broker truth for THIS book -- not for whichever account
            # happened to be bound first. Cached per book for the tick.
            if r.get("broker") == "alpaca":
                alpaca_held = await book_scope.held_symbols(
                    str(r.get("user_id") or ""), where="monitor")
            else:
                alpaca_held = None

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
                    # Crypto trail-to-lock for Alpaca-routed rows (Part 2/2b):
                    # HODL ratchets a trailing stop up (no target, keeps
                    # holding); SWING keeps its target but step-ladders the
                    # stop up to lock return-on-capital on the way there.
                    _strat_a = (r.get("strategy") or "").lower()
                    # 2026-08-17: this was an if/elif chain, and a chain is
                    # how crypto DCA ended up with ladder rungs but no trail
                    # between them -- the continuous trail was hand-wired to
                    # SWING and later SCALP, and DCA was simply never added.
                    # DCA's first rung is +3% against a ~6% target, so every
                    # gain under +3% round-tripped by construction. That is
                    # the XRP giveback. Each strategy now DECLARES what it
                    # wants (asset_policy.TRAIL_POLICIES) and this reads it,
                    # so a new strategy cannot be silently left out.
                    _tp = _trail_policy(_strat_a)
                    if r["side"] == "long" and "hodl" in _strat_a:
                        # A HODL is meant to ride: its own +40%/20% trail and
                        # the catastrophe stop, deliberately no giveback trail.
                        _t = await _maybe_trail_hodl(r, price_c)
                        if _t is not None:
                            stop_c = _t
                    elif r["side"] == "long" and "swing" in _strat_a:
                        from app.strategies.crypto import SWING_PROFIT_LADDER
                        _tl = await _maybe_ladder_stop(r, price_c, SWING_PROFIT_LADDER)
                        if _tl is not None:
                            stop_c = _tl
                        # Mike 2026-07-16 (the ETH 33%-giveback alert):
                        # between ladder rungs the giveback could eat most
                        # of a run. The CONTINUOUS profit-lock trail from
                        # the stock side now ratchets crypto stops too --
                        # locks (1 - 30%) of the peak gain, never lowers,
                        # so a pullback still books ~70% of the best gain.
                        _tt = await _maybe_trail_stock_profit(r, price_c)
                        if _tt is not None and (stop_c is None or _tt > stop_c):
                            stop_c = _tt
                    elif r["side"] == "long" and "dca" in _strat_a:
                        from app.strategies.crypto import DCA_PROFIT_LADDER
                        _td = await _maybe_ladder_stop(r, price_c, DCA_PROFIT_LADDER)
                        if _td is not None:
                            stop_c = _td
                        # The missing half of the DCA rules (8/17 audit).
                        if _tp.continuous_trail:
                            _tdt = await _maybe_trail_stock_profit(
                                r, price_c, min_gain=_tp.trail_arm_gain)
                            if _tdt is not None and (stop_c is None or _tdt > stop_c):
                                stop_c = _tdt
                    elif r["side"] == "long" and "scalp" in _strat_a:
                        # EXIT REPAIR, 2026-08-05. Scalps had NO trail at all --
                        # only the net-edge auto-exit below, which closed them
                        # the instant a gain covered round-trip cost. Mike's
                        # stated intent for that level was the opposite: "it was
                        # supposed to protect it from a loss not to take a win
                        # at that rate under 1 percent."
                        #
                        # So the level now ARMS BREAKEVEN and the position is
                        # given the same 30%-giveback profit trail swings
                        # already use. Order of precedence is Mike's: trail
                        # first, net-edge last and only as protection.
                        try:
                            from app.strategies.crypto import (
                                clears_fee_edge as _cfe0)
                            from app.paper.engine import (
                                CRYPTO_COMMISSION_BPS as _F0, SLIPPAGE_BPS as _S0)
                            _e0 = float(r.get("entry_price") or 0)
                            if _e0 > 0:
                                _g0 = (price_c - _e0) / _e0
                                if _cfe0(_g0, _F0, _S0) and (
                                        stop_c is None or _e0 > stop_c):
                                    stop_c = _e0     # breakeven: cannot lose now
                        except Exception:  # noqa: BLE001
                            pass
                        _ts = await _maybe_trail_stock_profit(
                            r, price_c, min_gain=SCALP_TRAIL_MIN_GAIN)
                        if _ts is not None and (stop_c is None or _ts > stop_c):
                            stop_c = _ts
                    elif r["side"] == "long" and _tp.continuous_trail:
                        # Anything not named above -- a new crypto strategy,
                        # a hand-tagged row, a reconciled import -- still
                        # gets the shared profit trail instead of nothing.
                        _tg = await _maybe_trail_stock_profit(
                            r, price_c, min_gain=_tp.trail_arm_gain)
                        if _tg is not None and (stop_c is None or _tg > stop_c):
                            stop_c = _tg
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
                    # Scalp net-edge auto-exit (Mike 2026-06-15): fast/quick plays take
                    # profit once they clear round-trip cost + the 0.01% net floor.
                    # SCALP only; HODL/SWING/DCA keep their ladders.
                    # RETIRED 2026-08-05. This closed a scalp the moment its
                    # gain covered round-trip cost -- 0.63% against a 1.8%
                    # stop, a geometry of 1:0.35 AGAINST, needing a 74% win
                    # rate to break even while the lane ran at 34%. The cost
                    # work (Harris) showed it sat BELOW its own cost bar in
                    # the friendliest market and closed at a loss outright in
                    # a thin one. Breakeven-arming plus the trail replaces it
                    # above. Set TREZO_SCALP_NET_EDGE_EXIT=1 to restore the
                    # old behaviour instantly if this proves wrong.
                    if (reason_c is None and "scalp" in _strat_a
                            and os.getenv("TREZO_SCALP_NET_EDGE_EXIT", "0") == "1"):
                        try:
                            from app.strategies.crypto import clears_fee_edge as _cfe2
                            from app.paper.engine import (
                                CRYPTO_COMMISSION_BPS as _FEE2, SLIPPAGE_BPS as _SLIP2,
                            )
                            _ec = float(r.get("entry_price") or 0)
                            if _ec > 0:
                                _g = ((price_c - _ec) / _ec if r["side"] == "long"
                                    else (_ec - price_c) / _ec)
                                if _cfe2(_g, _FEE2, _SLIP2):
                                    reason_c = "scalp_net_edge"
                        except Exception:
                            pass
                    # Step-profit ladder for CRYPTO (2026-08-17). Broker-
                    # routed crypto reached none of this: the only step
                    # call sat further down behind `at == "stock"`, so a
                    # coin could run the whole way to its target and bank
                    # nothing on the way. Same ladder, same env knobs, same
                    # daily-goal nudge -- sized by the asset policy, which
                    # knows coins are fractional and the venue never shuts.
                    if (reason_c is None and r["side"] == "long"
                            and os.getenv("TREZO_PROFIT_STEP_CRYPTO", "1") != "0"
                            and os.getenv("TREZO_PROFIT_STEP_ENABLED", "1") != "0"):
                        try:
                            _ec = float(r.get("entry_price") or 0)
                            _tc = float(r.get("target_price") or 0)
                            _qc = float(r.get("quantity") or 0)
                            _polc = _asset_policy(at)
                            if (_ec > 0 and _tc > _ec and price_c > _ec
                                    and _polc.can_step(_qc)):
                                _runc = (price_c - _ec) / (_tc - _ec)
                                _at0c, _fracc = _step_profile(_ec * _qc)
                                _okc, _nc = await _step_check(
                                    str(r.get("id")), r.get("user_id"),
                                    _runc, at0_override=_at0c)
                                if _okc:
                                    _stepped_c, _notec = await _alpaca_profit_step(
                                        r, price_c, frac=_fracc)
                                    _notec = f"step {_nc + 1}: {_notec}"
                                    if _stepped_c:
                                        _step_mark(str(r.get("id")))
                                        affected_users.add(r["user_id"])
                                        out.append(AgentMessage(
                                            agent=self.name, kind="info",
                                            payload={
                                                "user_id": r["user_id"],
                                                "ticker": tk,
                                                "note": f"Profit step: {_notec}",
                                                "position_id": r["id"],
                                                "broker": "alpaca",
                                            }))
                                    try:
                                        from app.agents.activity_log import record as _arecc
                                        _arecc("profit_step" if _stepped_c
                                               else "profit_step_abort", tk,
                                               strategy=(r.get("strategy") or ""),
                                               reason=_notec,
                                               extra={"user_id": str(r.get("user_id")),
                                                      "broker": "alpaca"})
                                    except Exception:  # noqa: BLE001
                                        pass
                                    if _stepped_c:
                                        continue
                        except Exception:  # noqa: BLE001
                            pass

                    if reason_c is None:
                        alpaca_managed += 1
                        continue
                    _liq, _cstat = await _throttled_liquidate(
                        tk, asset_type="crypto")
                    if _cstat in ("throttled", "circuit_open"):
                        alpaca_managed += 1
                        continue
                    liq_err = _cstat[6:] if _cstat.startswith("error:") else None
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
                    # Fresh-row grace (2026-06-12: at the open, WMT/GM/
                    # CSCO/SOFI were "closed" 6-60s after submission --
                    # the order had not FILLED yet, so the positions API
                    # did not list the symbol and this branch phantom-
                    # closed the row; the fill then landed and the shares
                    # sat orphaned until the 30-min reconcile re-imported
                    # them WITHOUT their strategy tags). A just-submitted
                    # order needs time to appear: skip reconcile-close
                    # for rows younger than 5 minutes.
                    if _minutes_since(r.get("entry_at")) < 5.0:
                        alpaca_managed += 1
                        continue
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
                                _liq, _liq_st = await _throttled_liquidate(tk)
                                if _liq_st in ("throttled", "circuit_open"):
                                    continue
                                liq_err = _liq_st[6:] if _liq_st.startswith("error:") else None
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

                    # Profit stepping for Alpaca-held stock longs (Mike
                    # 2026-07-02: partial selling controls drawdown). The
                    # broker-side twin of the modeled stepping: cancel legs
                    # -> sell slice -> OCO re-protect, verified at each step.
                    # 2026-08-17: was `at == "stock"` -- true by accident of
                    # history, not by decision, and the reason crypto never
                    # banked a slice. The registry answers now, so options,
                    # futures, bonds and a 401k sleeve each get the behaviour
                    # someone actually chose for them.
                    _pol2 = _asset_policy(at)
                    if (os.getenv("TREZO_PROFIT_STEP_ALPACA", "1") != "0"
                            and os.getenv("TREZO_PROFIT_STEP_ENABLED", "1") != "0"
                            and _pol2.supports_partial_step
                            and r["side"] == "long"):
                        try:
                            _e2 = float(r.get("entry_price") or 0)
                            _t2 = float(r.get("target_price") or 0)
                            _q2 = float(r.get("quantity") or 0)
                            if _e2 > 0 and _t2 > _e2 and _pol2.can_step(_q2):
                                price_ps = await _price(tk, at)
                                _run2 = ((price_ps - _e2) / (_t2 - _e2)
                                         if price_ps is not None else -1.0)
                                _at02, _frac2 = _step_profile(_e2 * _q2)
                                _ok2, _n2 = (await _step_check(
                                    str(r.get("id")), r.get("user_id"), _run2,
                                    at0_override=_at02)
                                    if price_ps is not None and price_ps > _e2
                                    else (False, 0))
                                if _ok2:
                                    stepped, note = await _alpaca_profit_step(
                                        r, price_ps, frac=_frac2)
                                    note = f"step {_n2 + 1}: {note}"
                                    if stepped:
                                        _step_mark(str(r.get("id")))
                                        affected_users.add(r["user_id"])
                                        out.append(AgentMessage(
                                            agent=self.name, kind="info",
                                            payload={
                                                "user_id": r["user_id"],
                                                "ticker": tk,
                                                "note": f"Profit step: {note}",
                                                "position_id": r["id"],
                                                "broker": "alpaca",
                                            }))
                                    try:
                                        from app.agents.activity_log import record as _arec
                                        _arec("profit_step" if stepped else "profit_step_abort",
                                              tk, strategy=(r.get("strategy") or ""),
                                              reason=note,
                                              extra={"user_id": str(r.get("user_id")),
                                                     "broker": "alpaca"})
                                    except Exception:  # noqa: BLE001
                                        pass
                                    if stepped:
                                        continue
                        except Exception:  # noqa: BLE001
                            pass

                    # Extended trailing step-ladder (crypto Part 2b ext,
                    # 2026-06-13): lock return-on-capital as a stock swing
                    # runs. Ratchet the stop up by the ladder; if price has
                    # fallen back to the locked stop, close at market (cancel
                    # legs first) -- the same client-side liquidation pattern
                    # the time stops use, so it works on Alpaca-routed rows
                    # whose real stop lives in the broker bracket.
                    if strat_a.startswith("extended"):
                        price_x = await _price(tk, at)
                        if price_x is not None:
                            from app.strategies.crypto import EXTENDED_PROFIT_LADDER
                            await _maybe_ladder_stop(r, price_x, EXTENDED_PROFIT_LADDER)
                            _xstop = float(r["stop_price"]) if r.get("stop_price") else None
                            if _xstop is not None and price_x <= _xstop:
                                _xliq, _x_st = await _throttled_liquidate(tk)
                                if _x_st in ("throttled", "circuit_open"):
                                    continue
                                _xerr = _x_st[6:] if _x_st.startswith("error:") else None
                                out.append(AgentMessage(
                                    agent=self.name, kind="info",
                                    payload={
                                        "user_id": r["user_id"], "ticker": tk,
                                        "note": ("Extended trailing-lock stop hit - "
                                                 "Alpaca position closed at market"
                                                 + (f" (error: {_xerr})" if _xerr else "")),
                                        "position_id": r["id"], "broker": "alpaca",
                                        "reason": "trail_lock",
                                    }))
                                continue

                    if strat_a.startswith("extended") and held_days >= SWING_MAX_HOLD_DAYS:
                        _liq, _liq_st = await _throttled_liquidate(tk)
                        if _liq_st in ("throttled", "circuit_open"):
                            continue
                        liq_err = _liq_st[6:] if _liq_st.startswith("error:") else None
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
                                _enforced = False
                                _pn = await _price(tk, at)
                                _sp = float(r["stop_price"]) if r.get("stop_price") else None
                                _tp = float(r["target_price"]) if r.get("target_price") else None
                                _hit = None
                                if _pn is not None:
                                    if r["side"] == "long":
                                        if _sp is not None and _pn <= _sp:
                                            _hit = "stop"
                                        elif _tp is not None and _pn >= _tp:
                                            _hit = "target"
                                    else:
                                        if _sp is not None and _pn >= _sp:
                                            _hit = "stop"
                                        elif _tp is not None and _pn <= _tp:
                                            _hit = "target"
                                if _hit is not None:
                                    _ol, _ost = await _throttled_liquidate(tk)
                                    if _ost == "ok":
                                        _enforced = True
                                        out.append(AgentMessage(
                                            agent=self.name, kind="info",
                                            payload={"user_id": r["user_id"], "ticker": tk,
                                                "note": (f"Orphan/naked {_hit} hit - enforced "
                                                         f"exit at market (was unmanaged)."),
                                                "position_id": r["id"], "broker": "alpaca",
                                                "reason": f"orphan_{_hit}"}))
                                if not _enforced:
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

            # Crypto trail-to-lock (crypto Part 2 / 2b, 2026-06-13):
            #  - HODL: ratchet a trailing stop UP after a big run; no target,
            #    so it keeps holding -- only the trailed stop or a manual
            #    close exits.
            #  - SWING: a defined trade, so it keeps its fixed target but
            #    step-ladders the stop up to lock return-on-capital in stages,
            #    so a reversal before the target still banks most of the gain.
            if at == "crypto" and side == "long":
                if "hodl" in strat:
                    _trail = await _maybe_trail_hodl(r, price)
                    if _trail is not None:
                        stop = _trail
                elif "swing" in strat:
                    from app.strategies.crypto import SWING_PROFIT_LADDER
                    _lad = await _maybe_ladder_stop(r, price, SWING_PROFIT_LADDER)
                    if _lad is not None:
                        stop = _lad
                elif "dca" in strat:
                    from app.strategies.crypto import DCA_PROFIT_LADDER
                    _ld = await _maybe_ladder_stop(r, price, DCA_PROFIT_LADDER)
                    if _ld is not None:
                        stop = _ld

            if at == "stock" and side in ("long", "short") and STOCK_TRAIL_ENABLED:
                _strail = await _maybe_trail_stock_profit(r, price)
                if _strail is not None:
                    stop = _strail

            # Continuous re-evaluation (Mike 6/29). Re-judges this position
            # with the shared capability library and actively manages it
            # (tighten stop / lower target / rotate / advise add). Master-
            # flagged OFF, so this is a no-op until enabled -- live behavior
            # is unchanged today.
            reeval_close: str | None = None
            if reeval_is_enabled():
                try:
                    _rv = await reevaluate_position(
                        r, price, side, at, strat, stop, target,
                        emit=out, agent_name="reevaluator",
                    )
                    if _rv:
                        if _rv.get("stop") is not None:
                            stop = _rv["stop"]
                        if _rv.get("target") is not None:
                            target = _rv["target"]
                        reeval_close = _rv.get("close")
                except Exception as _re:  # noqa: BLE001
                    out.append(AgentMessage(agent=self.name, kind="info",
                               payload={"note": f"reeval error: {str(_re)[:120]}"}))

            close_reason: str | None = None
            close_detail = ""
            # QW1: an explicit user close request takes priority.
            if r.get("close_requested"):
                close_reason, close_detail = "manual", "manual_close"
            elif reeval_close:
                close_reason, close_detail = "reeval", reeval_close
            if close_reason is None:
                if side == "long":
                    if stop is not None and price <= stop:
                        close_reason = "stop"
                        try:
                            _e = float(r.get("entry_price") or 0)
                            if at == "stock" and _e and stop > _e:
                                close_detail = "profit_lock"
                        except (TypeError, ValueError):
                            pass
                    elif target is not None and price >= target:
                        close_reason = "target"
                else:  # short
                    if stop is not None and price >= stop:
                        close_reason = "stop"
                        try:
                            _e = float(r.get("entry_price") or 0)
                            if at == "stock" and _e and stop < _e:
                                close_detail = "profit_lock"
                        except (TypeError, ValueError):
                            pass
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

            # Profit stepping (Mike 2026-07-02): bank HALF once the move
            # has covered most of the trip to target; the rest rides the
            # trail. Modeled rows only in v1 -- Alpaca partials must
            # renegotiate bracket legs first (queued, cancel-legs lesson
            # 6/12). Tunables: TREZO_PROFIT_STEP_ENABLED / _AT / _FRACTION.
            if (close_reason is None and side == "long"
                    and r.get("broker") != "alpaca"
                    and os.getenv("TREZO_PROFIT_STEP_ENABLED", "1") != "0"):
                try:
                    _e = float(r.get("entry_price") or 0)
                    _q = float(r.get("quantity") or 0)
                    _big_enough = _asset_policy(at).can_step(_q)
                    if (_e > 0 and _q > 0 and _big_enough
                            and target is not None and float(target) > _e):
                        _run = (price - _e) / (float(target) - _e)
                        _at0, _frac = _step_profile(_e * _q)
                        _ok_step, _n_prev = await _step_check(
                            str(r.get("id")), r.get("user_id"), _run,
                            at0_override=_at0)
                        if _ok_step:
                            from app.paper.engine import close_partial_position
                            _pf = await close_partial_position(
                                r["user_id"], r["id"], _frac, price,
                                reason="profit_step")
                            if _pf.ok:
                                _step_mark(str(r.get("id")))
                                affected_users.add(r["user_id"])
                                try:
                                    from app.agents.activity_log import record as _arec
                                    _arec("profit_step", tk, strategy=strat,
                                          reason=(f"step {_n_prev + 1}: banked "
                                                  f"{_frac * 100:.0f}% of remaining at "
                                                  f"{_run * 100:.0f}% of the run to "
                                                  f"target (${_pf.realized_pnl_usd:+.2f}); "
                                                  f"rest rides on"),
                                          extra={"user_id": str(r.get("user_id"))})
                                except Exception:  # noqa: BLE001
                                    pass
                except Exception:  # noqa: BLE001
                    pass

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
