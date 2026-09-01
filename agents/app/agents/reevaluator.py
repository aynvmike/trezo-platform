"""Continuous position re-evaluation engine (Mike 2026-06-29).

Re-judges every OPEN position on each monitor tick using the shared
capability library, and -- when enabled -- actively manages it back toward
profit: tighten the stop, lower an unrealistic target so it can still exit
green, rotate dead capital into a better setup, or (staged) average down.

Design principles:
  * SAFE BY DEFAULT. The master switch TREZO_REEVAL_ENABLED defaults OFF, so
    importing/calling this module is a no-op until it is turned on. Every
    sub-action has its own flag and every threshold is tunable through
    pydantic Settings (agents/.env) with a process-env fallback (G19).
  * PROTECTIVE DIRECTION ONLY for stops: a tightened stop always moves CLOSER
    to price (cuts risk); it never widens.
  * GREEN-ONLY for targets: a lowered target must still sit in profit above
    entry, so "banking a recovery" can never lock in a loss.
  * LEARN: every action is logged to the agent feed + shared memory, so the
    reasoning is visible on the Trading page and the agents accumulate
    experience over time.
  * One action per position per cooldown window, to avoid thrashing.

Averaging-down is recognised here but only ADVISES (logs a recommendation);
placing the actual add order is a separate, separately-capped part.
"""
from __future__ import annotations

import os
import time as _time
from datetime import datetime, timezone

from app.agents.base import AgentMessage
from app.config import get_settings
from app.runtime.capabilities import peak_giveback_pct


def _flag(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() not in ("0", "false", "no", "off", "")


def _num(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


# --- master + per-action switches -----------------------------------------
# Read through pydantic Settings so agents/.env reliably controls them: this
# app loads .env via Settings, NOT os.environ, so a bare os.getenv would miss
# .env. Falls back to a real env var, then the default. Master OFF until set.
def _settings_flag(attr: str, env: str, default: bool) -> bool:
    try:
        from app.config import get_settings
        v = getattr(get_settings(), attr, None)
        if v is not None:
            return bool(v)
    except Exception:  # noqa: BLE001
        pass
    return _flag(env, "1" if default else "0")


def reeval_is_enabled() -> bool:
    """Master switch -- True only when TREZO_REEVAL_ENABLED is set in
    agents/.env (or the environment). Default OFF."""
    return _settings_flag("trezo_reeval_enabled", "TREZO_REEVAL_ENABLED", False)


def _settings_num(attr: str, env: str, default: float) -> float:
    """Numeric twin of _settings_flag: Settings attr -> env var -> default.
    G19: the numeric tunables below were read with a bare os.getenv at
    IMPORT time, which never sees agents/.env (pydantic loads that file
    into Settings, not into os.environ) -- so every .env override was
    silently ignored while the bool flags next to them worked."""
    try:
        from app.config import get_settings
        v = getattr(get_settings(), attr, None)
        if v is not None:
            return float(v)
    except Exception:  # noqa: BLE001
        pass
    return _num(env, default)


# --- tunable bounds --------------------------------------------------------
# name -> (Settings attr, env var, default). Read per call via tunable(),
# never at import (G19). Defaults are unchanged from the import-time
# constants they replace. NOTE: app/config.py does not yet declare the
# numeric attrs, so until it does the Settings branch yields None and the
# value comes from the process env, then the default -- same as before,
# but now one config.py line away from honouring agents/.env.
_TUNABLES: dict[str, tuple[str, str, float]] = {
    "COOLDOWN_SEC": ("trezo_reeval_cooldown_sec", "TREZO_REEVAL_COOLDOWN_SEC", 900),
    "STALE_DAYS": ("trezo_reeval_stale_days", "TREZO_REEVAL_STALE_DAYS", 3),
    "ROTATE_DAYS": ("trezo_reeval_rotate_days", "TREZO_REEVAL_ROTATE_DAYS", 7),
    "TIGHTEN_GIVEBACK": ("trezo_reeval_tighten_giveback", "TREZO_REEVAL_TIGHTEN_GIVEBACK", 0.30),
    "TIGHTEN_BAND": ("trezo_reeval_tighten_band", "TREZO_REEVAL_TIGHTEN_BAND", 0.02),
    "TARGET_FAR_PCT": ("trezo_reeval_target_far_pct", "TREZO_REEVAL_TARGET_FAR_PCT", 0.08),
    "TARGET_REACH_BAND": ("trezo_reeval_target_reach_band", "TREZO_REEVAL_TARGET_REACH_BAND", 0.02),
    "MIN_BANK_PROFIT": ("trezo_reeval_min_bank_profit", "TREZO_REEVAL_MIN_BANK_PROFIT", 0.005),
    "AVGDOWN_TRIGGER": ("trezo_reeval_avgdown_trigger", "TREZO_REEVAL_AVGDOWN_TRIGGER", 0.08),
}


def tunable(name: str) -> float:
    attr, env, default = _TUNABLES[name]
    return _settings_num(attr, env, default)


_last_action: dict[str, float] = {}
_shadow_at: dict[str, float] = {}   # reprice-shadow log throttle (7/20)
_hb_at: dict[str, float] = {}   # visibility heartbeat throttle (7/1)


def _supabase():
    s = get_settings()
    if not s.supabase_url or not s.supabase_service_role_key:
        return None
    try:
        from supabase import create_client
        return create_client(s.supabase_url, s.supabase_service_role_key)
    except Exception:  # noqa: BLE001
        return None


def _pf(n: float) -> str:
    return ("$" + format(n, ",.0f")) if n >= 1000 else ("$" + format(n, ".2f"))


def _held_days(entry_at) -> float:
    try:
        dt = datetime.fromisoformat(str(entry_at).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0)
    except Exception:  # noqa: BLE001
        return 0.0


def _regime() -> str:
    try:
        from app.runtime.scope import get_scope
        return str(getattr(get_scope(), "regime", "neutral") or "neutral")
    except Exception:  # noqa: BLE001
        return "neutral"


def _low_edge(strategy: str, asset_type: str) -> bool:
    """Best-effort: does outcome-weighting say avoid this strategy? Defaults
    False so it never blocks on missing data."""
    try:
        from app.learning.strategy_weighting import strategy_disposition
        return str(strategy_disposition(strategy, asset_type)).lower() == "avoid"
    except Exception:  # noqa: BLE001
        return False


async def _persist(rid, **fields) -> bool:
    client = _supabase()
    if client is None or not fields:
        return False
    import asyncio

    def _upd():
        return client.table("paper_positions").update(fields).eq("id", rid).execute()
    try:
        await asyncio.to_thread(_upd)
        return True
    except Exception:  # noqa: BLE001
        return False


async def _log(emit, agent_name, user_id, ticker, action, reason) -> None:
    # Visibility pack (2026-07-01): every re-eval ACTION also lands in the
    # local activity log so Mike can see the engine working.
    try:
        from app.agents.activity_log import record as _arec
        _arec(f"reeval_{action}", ticker, reason=reason,
              extra={"user_id": str(user_id or "shared")})
    except Exception:  # noqa: BLE001
        pass
    try:
        emit.append(AgentMessage(
            agent=agent_name, kind="info",
            payload={"event": "reeval_action", "ticker": ticker, "action": action,
                     "note": reason, "user_id": user_id},
        ))
    except Exception:  # noqa: BLE001
        pass
    try:
        import asyncio
        client = _supabase()
        if client is None:
            return
        now = datetime.now(timezone.utc).isoformat()

        def _ins():
            return client.table("agent_memory").insert({
                "agent": "reevaluator", "scope": str(user_id or "shared"),
                "topic": f"reeval:{ticker}", "category": "reeval",
                "content": f"{action}: {reason}", "weight": 1.0,
                "created_at": now, "updated_at": now,
            }).execute()
        await asyncio.to_thread(_ins)
    except Exception:  # noqa: BLE001
        pass


def _collapse_bar(user_id):
    """This book's TCS entry bar (0-100) for the collapse check, or None
    when the settings read raises. G4: None means "do not judge" -- the
    caller skips the collapse check rather than closing on a data
    failure. A row with no threshold set falls to the 70 default."""
    try:
        from app.runtime.settings import get_bot_settings
        return int(get_bot_settings(user_id).tcs_threshold or 70)
    except Exception:  # noqa: BLE001
        return None


async def reevaluate_position(r, price, side, at, strat, stop, target,
                              emit, agent_name="reevaluator"):
    """Re-judge one open position. Returns {"stop"?, "target"?, "close"?} when
    an action is taken, else None. Persists stop/target changes itself and logs
    every action. Fail-open: any error returns None."""
    try:
        if not reeval_is_enabled():
            return None
        # THE LONG-TERM LANE IS EXEMPT (AUDIT 2026-08-27, priority #2).
        # This function reads price-only gain -- no dividend term -- and
        # returns early on winners, so it acts ONLY on losers. An
        # ex-dividend date drops the price by the dividend and puts a
        # perfectly healthy ladder holding exactly where this code
        # looks for broken ones; reeval_tcs_collapse can then close it
        # outright after one day held. A buy-and-hold income position
        # judged by an intraday momentum lens on the one morning its
        # price mechanically dips is not a re-evaluation, it is a
        # misreading. The ladder manages its own exits (screen-based,
        # cut-triggered); the reevaluator manages the trading lanes.
        _rl_strat = str(strat or r.get("strategy") or "").lower()
        # "dividend_lt" EXACT lane prefix (2026-08-28): bare "dividend"
        # also matched dividend_capture_long — a live 2-7 day SWING with
        # a stop and target that NEEDS this management. Only the
        # buy-and-hold lane is exempt.
        if _rl_strat.startswith(("dividend_lt", "wheel", "income")):
            return None
        # G19: read the numeric tunables NOW, through Settings -> env ->
        # default, instead of the import-time os.getenv snapshot. These
        # names deliberately shadow nothing at module level any more;
        # every use below in this function resolves to these locals.
        COOLDOWN_SEC = tunable("COOLDOWN_SEC")
        STALE_DAYS = tunable("STALE_DAYS")
        ROTATE_DAYS = tunable("ROTATE_DAYS")
        TIGHTEN_GIVEBACK = tunable("TIGHTEN_GIVEBACK")
        TIGHTEN_BAND = tunable("TIGHTEN_BAND")
        TARGET_FAR_PCT = tunable("TARGET_FAR_PCT")
        TARGET_REACH_BAND = tunable("TARGET_REACH_BAND")
        MIN_BANK_PROFIT = tunable("MIN_BANK_PROFIT")
        AVGDOWN_TRIGGER = tunable("AVGDOWN_TRIGGER")
        pid = str(r.get("id"))
        now = _time.monotonic()
        last = _last_action.get(pid)
        if last is not None and (now - last) < COOLDOWN_SEC:
            return None
        try:
            entry = float(r.get("entry_price") or 0)
        except (TypeError, ValueError):
            return None
        if entry <= 0 or price <= 0:
            return None
        is_long = side == "long"
        gain = (price - entry) / entry if is_long else (entry - price) / entry
        # Winners are managed by the profit-trail elsewhere -- don't interfere.
        if gain > 0:
            return None

        user_id = r.get("user_id")
        ticker = str(r.get("ticker") or "?")
        held = _held_days(r.get("entry_at"))
        regime = _regime()
        stale = held >= STALE_DAYS
        very_stale = held >= ROTATE_DAYS
        low_edge = _low_edge(str(strat or ""), str(at or ""))
        tighten_on = _settings_flag("trezo_reeval_tighten_stop", "TREZO_REEVAL_TIGHTEN_STOP", True)
        lower_on = _settings_flag("trezo_reeval_lower_target", "TREZO_REEVAL_LOWER_TARGET", True)
        rotate_on = _settings_flag("trezo_reeval_rotate", "TREZO_REEVAL_ROTATE", True)
        avgdown_on = _settings_flag("trezo_reeval_average_down", "TREZO_REEVAL_AVERAGE_DOWN", False)

        giveback = 0.0
        try:
            peak_price = float(r.get("peak_price") or 0)
            if peak_price > 0:
                giveback = peak_giveback_pct(
                    (peak_price - entry) if is_long else (entry - peak_price),
                    (price - entry) if is_long else (entry - price),
                )
        except (TypeError, ValueError):
            giveback = 0.0

        # Visibility heartbeat + TCS RE-SCORE (2026-07-01/02): once per
        # position per hour, prove the re-check ran AND re-judge the thesis
        # with fresh candles (Mike's ask: re-evaluate TCS on held trades
        # even with a stop already in). A collapsed score is evidence the
        # setup is GONE -- rotate the capital instead of babysitting it.
        # Tunables: TREZO_REEVAL_TCS_RESCORE / TREZO_REEVAL_TCS_COLLAPSE_FRAC.
        try:
            if (now - _hb_at.get(pid, 0.0)) >= 3600.0:
                _hb_at[pid] = now
                fresh_tcs = None
                if _settings_flag("trezo_reeval_tcs_rescore",
                                  "TREZO_REEVAL_TCS_RESCORE", True):  # G19
                    try:
                        from app.data.candles import fetch_candles_for
                        from app.patterns.scoring import calculate_score
                        _cnd = await fetch_candles_for(ticker, str(at or "stock"))
                        if _cnd and len(_cnd) >= 15:
                            fresh_tcs = int(calculate_score(
                                _cnd, strategy=str(strat or "") or None).tcs)
                    except Exception:  # noqa: BLE001
                        fresh_tcs = None
                collapsed = False
                _thr = None   # this book's entry bar (0-100); None = unknown
                if fresh_tcs is not None:
                    _thr = _collapse_bar(user_id)
                    if _thr is None:
                        # G4: the settings read FAILED. The old fallback
                        # was 700 on a 0-100 scale, so fresh_tcs < 350
                        # was always true and a data failure force-closed
                        # the position. Cannot know the bar -> cannot
                        # judge a collapse -> skip the check, say so.
                        collapsed = False
                    else:
                        _cfrac = _settings_num(
                            "trezo_reeval_tcs_collapse_frac",
                            "TREZO_REEVAL_TCS_COLLAPSE_FRAC", 0.5)  # G19
                        collapsed = fresh_tcs < int(_thr * _cfrac)
                from app.agents.activity_log import record as _arec
                _arec("reeval_check", ticker, tcs=fresh_tcs,
                      strategy=str(strat or ""),
                      reason=(f"down {abs(gain) * 100:.1f}%, held {held:.1f}d, "
                              f"giveback {giveback * 100:.0f}%, regime {regime}"
                              + ((f"; fresh TCS {fresh_tcs} vs bar {_thr}"
                                  if _thr is not None else
                                  f"; fresh TCS {fresh_tcs}, bar UNKNOWN "
                                  "(settings read failed) -- collapse "
                                  "check skipped")
                                 if fresh_tcs is not None else "")
                              + (" -- thesis COLLAPSED" if collapsed else "")),
                      extra={"user_id": str(user_id or "shared")})
                if rotate_on and collapsed and held >= 1.0:
                    reason = (f"{ticker}: fresh TCS {fresh_tcs} is below half the "
                              f"entry bar ({_thr}) after {held:.1f}d, down "
                              f"{abs(gain) * 100:.1f}% -- the setup is gone; "
                              f"rotating the capital out.")
                    _last_action[pid] = now
                    await _log(emit, agent_name, user_id, ticker,
                               "rotate_tcs_collapse", reason)
                    return {"close": "reeval_tcs_collapse"}
        except Exception:  # noqa: BLE001
            pass
        try:
            cur_stop = float(stop) if stop is not None else None
        except (TypeError, ValueError):
            cur_stop = None
        try:
            cur_target = float(target) if target is not None else None
        except (TypeError, ValueError):
            cur_target = None

        # ---- 1) Rotate a dead position out -> free the capital -----------
        if rotate_on and (very_stale or (stale and (regime == "risk_off" or low_edge))):
            reason = (f"{ticker}: held {held:.0f}d, down {abs(gain) * 100:.1f}% and the edge has "
                      f"faded{' (risk-off)' if regime == 'risk_off' else ''} -- closing to free the "
                      f"capital for a higher-edge setup.")
            _last_action[pid] = now
            await _log(emit, agent_name, user_id, ticker, "rotate_out", reason)
            return {"close": "reeval_rotate"}

        # ---- 2) Average down (ADVISORY only this part) -------------------
        if (avgdown_on and regime != "risk_off" and not very_stale
                and gain <= -AVGDOWN_TRIGGER and is_long):
            reason = (f"{ticker}: down {abs(gain) * 100:.1f}% with the thesis still intact -- a measured "
                      f"add near {_pf(price)} would lower the cost basis. (Averaging-down is staged for "
                      f"the next part; not executed yet.)")
            _last_action[pid] = now
            await _log(emit, agent_name, user_id, ticker, "average_down_suggested", reason)
            return None

        # ---- 3) Lower an unrealistic target so it can exit green ---------
        # 2026-07-14 (Mike, the RBLX morning): a REVERSAL now also
        # triggers the reprice -- not just staleness. When the trade is
        # giving back its peak and the target sits far away, the sell
        # comes down to a reachable price instead of watching the move
        # walk away from it.
        if (lower_on and (stale or giveback >= TIGHTEN_GIVEBACK)
                and cur_target is not None):
            far = ((cur_target - price) / price) if is_long else ((price - cur_target) / price)
            # SHADOW MODE (Mike 2026-07-20): the 8% far-trigger looked
            # dead at this account size (7 of 9 round-trippers in the
            # last 30d sat UNDER it) -- but the knob does not move
            # without data. Log what a tighter trigger WOULD have done,
            # change nothing, and let the week's ledger decide.
            _sh_far = _settings_num("trezo_reeval_shadow_far_pct",
                                    "TREZO_REEVAL_SHADOW_FAR_PCT", 0.03)  # G19
            if _sh_far < TARGET_FAR_PCT and _sh_far < far <= TARGET_FAR_PCT:
                _shk = f"sh:{pid}"
                if now - _shadow_at.get(_shk, 0.0) > 6 * 3600:
                    _shadow_at[_shk] = now
                    if is_long:
                        _sh_t = round(max(entry * (1 + MIN_BANK_PROFIT),
                                          price * (1 + TARGET_REACH_BAND)), 4)
                    else:
                        _sh_t = round(min(entry * (1 - MIN_BANK_PROFIT),
                                          price * (1 - TARGET_REACH_BAND)), 4)
                    try:
                        from app.agents.activity_log import record as _shrec
                        _shrec("reprice_shadow", ticker,
                               strategy=str(r.get("strategy") or ""),
                               reason=(f"SHADOW: target {_pf(cur_target)} sits "
                                       f"{far * 100:.1f}% away (under the live "
                                       f"{TARGET_FAR_PCT * 100:.0f}% trigger); a "
                                       f"{_sh_far * 100:.0f}% trigger would have "
                                       f"lowered it to {_pf(_sh_t)}"),
                               extra={"position_id": str(r.get("id")),
                                      "price": price,
                                      "would_target": _sh_t,
                                      "cur_target": cur_target,
                                      "far_pct": round(far * 100, 2)})
                    except Exception:  # noqa: BLE001
                        pass
            if far > TARGET_FAR_PCT:
                if is_long:
                    new_t = round(max(entry * (1 + MIN_BANK_PROFIT), price * (1 + TARGET_REACH_BAND)), 4)
                    ok = new_t < cur_target and new_t >= entry * (1 + MIN_BANK_PROFIT)
                else:
                    new_t = round(min(entry * (1 - MIN_BANK_PROFIT), price * (1 - TARGET_REACH_BAND)), 4)
                    ok = new_t > cur_target and new_t <= entry * (1 - MIN_BANK_PROFIT)
                if ok:
                    reason = (f"{ticker}: target {_pf(cur_target)} was {far * 100:.0f}% away and unrealistic "
                              f"after {held:.0f}d -- lowered to {_pf(new_t)} so it can still exit green "
                              f"instead of round-tripping.")
                    await _persist(r.get("id"), target_price=new_t)
                    r["target_price"] = new_t
                    # Push the reprice to the BROKER (Mike 2026-07-14:
                    # DB-side lowers left the stale sell at Alpaca).
                    try:
                        from app.paper.leg_sync import resync_alpaca_legs
                        # TE-12: the resync binds the row's book itself.
                        await resync_alpaca_legs(r, why=reason[:110],
                                                 user_id=str(user_id or ""))
                    except Exception:  # noqa: BLE001
                        pass
                    _last_action[pid] = now
                    await _log(emit, agent_name, user_id, ticker, "lower_target", reason)
                    return {"target": new_t}

        # ---- 4) Tighten the stop to cut the loss sooner -----------------
        if tighten_on and (regime == "risk_off" or giveback >= TIGHTEN_GIVEBACK or stale):
            if is_long:
                new_s = round(price * (1 - TIGHTEN_BAND), 4)
                ok = new_s < price and (cur_stop is None or new_s > cur_stop)
            else:
                new_s = round(price * (1 + TIGHTEN_BAND), 4)
                ok = new_s > price and (cur_stop is None or new_s < cur_stop)
            if ok:
                why = ("risk-off" if regime == "risk_off"
                       else f"giving back {giveback * 100:.0f}% of its peak" if giveback >= TIGHTEN_GIVEBACK
                       else f"stalled {held:.0f}d")
                reason = (f"{ticker}: thesis weakening ({why}) -- tightened the stop to {_pf(new_s)} "
                          f"to cut the loss sooner.")
                await _persist(r.get("id"), stop_price=new_s)
                r["stop_price"] = new_s
                # Push the tightened stop to the BROKER too.
                try:
                    from app.paper.leg_sync import resync_alpaca_legs
                    # TE-12: the resync binds the row's book itself.
                    await resync_alpaca_legs(r, why=reason[:110],
                                             user_id=str(user_id or ""))
                except Exception:  # noqa: BLE001
                    pass
                _last_action[pid] = now
                await _log(emit, agent_name, user_id, ticker, "tighten_stop", reason)
                return {"stop": new_s}

        return None
    except Exception:  # noqa: BLE001
        return None
