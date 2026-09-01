"""Operations Watchdog - the supervisor. (It was the 21st agent when
written; the registry holds 30 as of 2026-08-27 — EXPECTED_AGENTS below
is the authoritative roster.)

Mike's insight 2026-06-03: when the bootstrap silently registers 0
agents (and we don't notice for 4 days), the system fails open. No
trades, no alerts, no signal that anything is wrong - the FastAPI
service is healthy on /health but the agents themselves never started.

This agent watches the agent layer. Every 5 minutes it:

  1. Cross-references the runtime registry against a list of agents
     we EXPECT to be loaded. Any agent missing from the registry
     gets a critical alert.

  2. For each registered agent, checks `last_tick_at`. If a scanner
     has been silent for longer than its tolerance during US market
     hours, raise an alert. Event-driven agents (tick_interval_seconds
     <= 0) never tick by design and are exempt from this check
     outright (REG-05).

  3. Persists alerts to the `ops_health_alerts` table (RLS off - this
     is platform-level monitoring, not per-user). The UI surfaces
     these as a "System health" panel on the Trading page.

  4. FLOW SENSOR, per lane (NET2-GLOBAL / NET2-COUNT-BEFORE-KILL):
     tallies signals, approves, vetoes, executes, execution kills and
     handler crashes off the bus, keyed by lane (stock / crypto /
     option / ...), and alarms per lane when signals produce no
     approvals or when approvals produce no fills (NET2-REV-01). See
     _check_flow(). There is no auto-tick and never was: the watchdog
     alerts, a human (or the ops relay) restarts.

What this CANNOT do:
  - Recover from a complete bootstrap failure (it can't tick if it's
    not registered itself). For that case, see the README-level
    instructions: check the start-agents.bat output window for the
    Python traceback at boot.

Wired by Nova for Mike on 2026-06-03 (Task #31).
"""

from __future__ import annotations

import asyncio
import logging
import os as _os
import time as _time
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from app.config import get_settings

from .base import Agent, AgentMessage


logger = logging.getLogger(__name__)


# The agents we EXPECT to be running. Each entry is (name,
# max_silence_during_market_minutes). Cross-strategy scanners get a
# 35-minute tolerance (they tick every 30 min normally); event-driven
# agents (Risk Manager, Trade Execution) get a longer tolerance
# because they only fire when something happens upstream.
EXPECTED_AGENTS: list[tuple[str, int]] = [
    ("pattern_detection", 35),
    ("stms_scanner", 35),
    ("orb_scanner", 35),
    ("extended_scanner", 35),
    ("crypto_scanner", 60),       # 24/7 strategy, lower urgency
    ("market_desk", 35),          # the report reader must never go quiet unnoticed
    # AUDIT 2026-08-27: six agents were registered but never
    # silence-checked -- including the BACKUP agent, whose death would
    # have stopped the hourly Supabase and weekly Dropbox copies with
    # no alarm. Tolerances sized to each tick interval.
    ("archivist", 45),            # 15-min tick; the backups must not die quietly
    ("broker_truth", 45),         # 15-min tick; options ledger truth
    ("book_health", 20),          # 5-min tick
    ("dividend_lt", 75),          # 30-min tick
    ("portfolio_architect", 750), # 6-hour tick
    ("forex_scanner", 20),        # 3-min tick; ticks even while dormant
    ("options_scanner", 65),      # 30-min tick + occasional skip
    ("risk_manager", 240),        # event-driven (interval 0): Check 1 only, REG-05
    ("trade_execution", 240),     # event-driven (interval 0): Check 1 only, REG-05
    ("position_monitor", 30),     # ticks frequently
    ("exit_advisor", 30),
    ("exit_advisor_options", 30),
    ("cycle_awareness", 360 + 60),  # ticks every 6h
    ("market_horizon", 35),
    ("market_sentiment", 60),
    ("research", 360 + 60),
    ("adaptive_scope", 60),
    ("dividend_manager", 360 + 60),
    ("tax_optimizer", 360 + 60),
    ("kindrip", 360 + 60),
    ("strategy_discovery", 360 + 60),
    ("user_support", 1440),       # event-driven (interval 0): Check 1 only, REG-05
    ("relay_ingest", 60),         # drains Nova's briefings every 5 min
    ("ops_watchdog", 10),         # this agent itself - silence detector
]


# Conservative US-equities open check. The watchdog ONLY raises silence
# alerts when the market is open - a scanner being quiet at 3 AM is
# expected. Crypto exception is handled below.
def _us_market_open(now: Optional[datetime] = None) -> bool:
    now = now or datetime.now(timezone.utc)
    # Convert UTC -> ET. DST ignored (EST = UTC-5, EDT = UTC-4). We err
    # on the side of "open" for the boundary hour to avoid false-negatives.
    et_hour = (now.hour - 4) % 24
    weekday = now.weekday()
    if weekday >= 5:  # Sat / Sun
        return False
    # Cover the wider session 8:30 AM - 4:30 PM ET.
    return 8 <= et_hour <= 16


def _supabase():
    s = get_settings()
    if not s.supabase_url or not s.supabase_service_role_key:
        return None
    try:
        from supabase import create_client
        return create_client(s.supabase_url, s.supabase_service_role_key)
    except Exception:  # noqa: BLE001
        return None


_BOOT_AT = datetime.now(timezone.utc)

# APPROVAL STARVATION (2026-08-31). Dull on purpose: a window must be at
# least this long and carry at least this many signals before silence
# counts as evidence. Tunable by env for a noisy or a very thin book.
FLOW_WINDOW_MIN = float(_os.getenv("TREZO_FLOW_WINDOW_MIN", "20") or 20)
FLOW_MIN_SIGNALS = int(float(_os.getenv("TREZO_FLOW_MIN_SIGNALS", "15") or 15))
# NET2-COUNT-BEFORE-KILL: alarm B needs at least this many approvals in
# the window before "every one of them died at execution" is evidence.
FLOW_MIN_APPROVES_FOR_KILL = 3

# NET2-GLOBAL: the flow counters are keyed by LANE. A single global
# count let one crypto approve (24/7 lane) silence a starving stock lane
# for the whole of the equity starvation. Lane comes from the payload:
# "lane" on execution outcomes, "asset_type" on signal/approve/veto
# (forex and dividend_lt stamp it); equity spellings fold to "stock".
#
# BOUND, not just built: the equity scanners (pattern_detection, stms,
# orb, extended) and crypto_scanner stamp NO asset_type at all, so an
# unlabelled message is classified exactly the way trade_execution
# classifies it before routing (its line "crypto if ticker in
# CRYPTO_SYMBOLS else stock", from the same COIN_MAP): the lanes the
# watchdog counts are the lanes the executor trades. A message with no
# ticker at all (heartbeats, import errors) is "unknown".
_LANE_ALIASES = {"us_equity": "stock", "stock": "stock", "stocks": "stock",
                 "etf": "stock", "equity": "stock"}
_CRYPTO_SYMBOLS: Optional[set] = None


def _crypto_symbols() -> set:
    global _CRYPTO_SYMBOLS
    if _CRYPTO_SYMBOLS is None:
        try:
            from app.data.candles import COIN_MAP
            _CRYPTO_SYMBOLS = {str(s).upper() for s in COIN_MAP.keys()}
        except Exception:  # noqa: BLE001
            _CRYPTO_SYMBOLS = {"XRP", "ETH", "SOL", "BTC"}
    return _CRYPTO_SYMBOLS


def _lane_of(payload: Any) -> str:
    if not isinstance(payload, dict):
        return "unknown"
    raw = payload.get("lane") or payload.get("asset_type")
    if raw:
        raw = str(raw).strip().lower()
        if raw:
            return _LANE_ALIASES.get(raw, raw)
    # Unlabelled: mirror trade_execution's own ticker-derived split.
    if str(payload.get("strategy") or "").lower().startswith("crypto"):
        return "crypto"
    ticker = str(payload.get("ticker") or "").strip().upper()
    if not ticker:
        return "unknown"
    if "/" in ticker or ticker in _crypto_symbols():
        return "crypto"
    return "stock"


def _new_lane_counters() -> dict[str, Any]:
    return {"signals": 0, "approves": 0, "vetoes": 0, "executes": 0,
            "kills": 0, "handler_fails": 0, "kill_reasons": {}}


def _lane_market_applies(lane: str, market_open: bool) -> bool:
    """Crypto trades around the clock; every other lane is judged only
    during US market hours so a quiet evening cannot cry wolf."""
    return True if lane == "crypto" else market_open


_JANITOR_DAY = ""   # daily agent_messages purge marker (2026-07-07)
_ALERT_ACK_HOUR = ""  # hourly stale-advisory auto-ack marker (2026-07-15)
_BRIEF_AM_DAY = ""    # market-brief once-a-day gates (2026-08-12)
_BRIEF_PM_DAY = ""


class OpsWatchdogAgent(Agent):
    """Supervisor / health monitor (roster: EXPECTED_AGENTS, 30 strong)."""

    name = "ops_watchdog"
    tick_interval_seconds = 300  # every 5 minutes

    def __init__(self) -> None:
        # In-memory dedupe: don't re-alert the same condition every tick
        # while it persists. Keyed by (alert_kind, target_name).
        self._open_alerts: set[tuple[str, str]] = set()
        # Flow counters (2026-08-31), keyed by LANE since NET2-GLOBAL.
        # {"since": epoch, "lanes": {lane: _new_lane_counters()}}.
        self._flow: dict[str, Any] = {"since": _time.time(), "lanes": {}}

    def _lane(self, name: str) -> dict[str, Any]:
        return self._flow["lanes"].setdefault(name, _new_lane_counters())

    async def on_message(self, message: AgentMessage) -> list[AgentMessage]:
        # Count the shape of the decision pipeline, PER LANE. Deliberately
        # free: no I/O, no awaits, just tallies read by _check_flow() on
        # the 5-minute tick. This is the sensor for the outage that ran
        # from 8/27 to 8/31 -- signals firing, nothing approved, and the
        # only visible messages were vetoes from checks upstream of the
        # crash. It runs on EVERY bus message, so it must never raise.
        try:
            k = message.kind
            p = message.payload if isinstance(message.payload, dict) else {}
            lane = self._lane(_lane_of(p))
            if k == "signal":
                lane["signals"] += 1
            elif k == "approve":
                lane["approves"] += 1
            elif k == "veto":
                lane["vetoes"] += 1
            elif k == "execute":
                lane["executes"] += 1
            elif k == "error":
                ev = p.get("event")
                if ev == "handler_failed":
                    lane["handler_fails"] += 1
                    # NET2-REV-01: the executor CRASHING on an approve is
                    # an approve that died at execution, not "nothing".
                    # bootstrap publishes handler_failed with agent +
                    # trigger_kind; without this arm a trade_execution
                    # that raised on every approve read as executes=0,
                    # kills=0 -- the 8/27 shape, one agent downstream.
                    if (str(p.get("agent") or "") == "trade_execution"
                            and str(p.get("trigger_kind") or "") == "approve"):
                        lane["kills"] += 1
                        reason = str(p.get("error")
                                     or "(executor crashed)")[:80]
                        rs = lane["kill_reasons"]
                        rs[reason] = rs.get(reason, 0) + 1
                elif ev == "execute_error" or (
                        ev is None
                        and getattr(message, "agent", "") == "trade_execution"
                        and "error" in p):
                    # NET2-COUNT-BEFORE-KILL: an approve that died at
                    # execution never came out the far end. Contract:
                    # trade_execution kind="error" with
                    # event="execute_error" and "lane"; the second arm
                    # also accepts the older event-less error shape.
                    lane["kills"] += 1
                    reason = str(p.get("error") or p.get("reason")
                                 or "(no reason given)")[:80]
                    rs = lane["kill_reasons"]
                    rs[reason] = rs.get(reason, 0) + 1
        except Exception:  # noqa: BLE001
            pass
        return []

    async def _check_flow(self) -> list[AgentMessage]:
        """Alarm, PER LANE, when signals go in and nothing comes out.

        THE CASE THIS EXISTS FOR (2026-08-31): risk_manager.on_message
        raised on every signal carrying a real direction. The router
        swallowed it, so there was no error to find -- the platform
        simply approved nothing for four trading days while the log
        looked merely quiet. Every other check here asks "is this agent
        ticking?" and every one of them said yes.

        Two shapes, each judged per lane:

          A. APPROVAL STARVATION -- at least FLOW_MIN_SIGNALS signals in
             the lane and zero approvals. The original check.
             NET2-GLOBAL: it used to count globally, so one crypto
             approve (a 24/7 lane) silenced it while the stock lane
             starved for days.
          B. EXECUTION STARVATION -- at least FLOW_MIN_APPROVES_FOR_KILL
             approvals and zero executes: the gate said yes and nothing
             filled. The note splits them into killed-with-a-reason
             (execute_error, or the executor crashing on the approve)
             and vanished (no outcome at all: a kind="info" skip, a
             disabled executor, a dropped message).
             NET2-COUNT-BEFORE-KILL: approvals were counted at approve
             time, so an approve killed at execution still read as "the
             pipeline works" through the whole equity starvation. The
             alert names the top kill reason. NET2-REV-01: the first
             cut required kills >= approves, which an approve that
             simply vanished could never satisfy.

        Thresholds are deliberately dull: the window must be at least
        FLOW_WINDOW_MIN long and each lane is judged only when its
        market applies (stock/option/...: US market hours; crypto:
        always), so a quiet morning cannot cry wolf.
        """
        out: list[AgentMessage] = []
        f = self._flow
        window_min = (_time.time() - f["since"]) / 60.0
        if window_min < FLOW_WINDOW_MIN:
            return out
        # Reset the window whatever we decide, so one bad window does not
        # poison the next one.
        lanes = dict(f.get("lanes") or {})
        self._flow = {"since": _time.time(), "lanes": {}}

        market_open = _us_market_open()
        for lane in sorted(lanes):
            if not _lane_market_applies(lane, market_open):
                continue
            try:
                out.extend(await self._judge_lane(lane, lanes[lane], window_min))
            except Exception as e:  # noqa: BLE001
                logger.warning("ops_watchdog flow check failed for lane %s: %s",
                               lane, e)
        return out

    async def _judge_lane(self, lane: str, c: dict[str, Any],
                          window_min: float) -> list[AgentMessage]:
        out: list[AgentMessage] = []
        signals, approves = int(c.get("signals", 0)), int(c.get("approves", 0))
        vetoes, hfails = int(c.get("vetoes", 0)), int(c.get("handler_fails", 0))
        executes, kills = int(c.get("executes", 0)), int(c.get("kills", 0))
        key_a = ("approval_starvation", lane)
        key_b = ("execution_starvation", lane)

        # ---- A: signals in, nothing approved ---------------------------
        if signals >= FLOW_MIN_SIGNALS and approves == 0:
            # Say which shape it is: accounted-for (every signal has a
            # veto) vs UNACCOUNTED, which is the dangerous one -- signals
            # going in and nothing at all coming out is a crash, not a
            # decision.
            unaccounted = max(0, signals - vetoes)
            shape = (f"{vetoes} veto(es) explain them"
                     if unaccounted == 0 else
                     f"{unaccounted} of them produced NO verdict at all -- "
                     f"not an approval, not a veto")
            msg = (
                f"APPROVAL STARVATION [{lane}]: {signals} signal(s) in "
                f"{window_min:.0f} min produced ZERO approvals on the "
                f"{lane} lane; {shape}"
                + (f"; {hfails} handler crash(es) reported" if hfails else "")
                + ". A silent pipeline is what the 8/27-8/31 outage looked "
                  "like: every agent ticking, nothing traded. Check "
                  "risk_manager first, then trade_execution."
            )
            await self._raise_flow(
                key_a, severity="urgent" if unaccounted else "warn",
                title=f"Trezo: nothing is being approved ({lane})", msg=msg)
            out.append(AgentMessage(
                agent=self.name, kind="error",
                payload={"event": "approval_starvation", "lane": lane,
                         "signals": signals, "approves": 0,
                         "vetoes": vetoes, "unaccounted": unaccounted,
                         "handler_failures": hfails,
                         "window_min": round(window_min, 1), "note": msg}))
        elif approves > 0:
            # NET2-REV-02: only RECOVERY (an approval) clears the dedupe.
            # A thin or empty window is inconclusive; clearing on it
            # re-pinged the webhook every other window while the lane
            # stayed starved. (The pre-NET2 global check had this right.)
            self._open_alerts.discard(key_a)

        # ---- B: approved, and NOTHING filled ---------------------------
        # NET2-REV-01: the audit shape was "kills >= approves", which is
        # blind to an approve that simply VANISHES -- trade_execution
        # crashing (handler_failed), disabled, or answering with a
        # kind="info" skip ("no paper accounts", "Supabase unavailable").
        # Approvals in, zero fills out is the alarm; the note says how
        # many died with a reason and how many produced no outcome at
        # all, the same accounted/unaccounted split alarm A makes.
        if approves >= FLOW_MIN_APPROVES_FOR_KILL and executes == 0:
            reasons = c.get("kill_reasons") or {}
            top, top_n = (max(reasons.items(), key=lambda kv: kv[1])
                          if reasons else ("(no reason given)", 0))
            unaccounted_b = max(0, approves - kills)
            shape_b = (
                f"{kills} died at execution; top kill reason ({top_n}x): {top}"
                if kills else "none of them produced an outcome at all")
            if kills and unaccounted_b:
                shape_b += (f"; {unaccounted_b} produced NO outcome at all "
                            f"-- not a fill, not a rejection")
            msg = (
                f"EXECUTION STARVATION [{lane}]: {approves} approval(s) in "
                f"{window_min:.0f} min produced ZERO fills on the {lane} "
                f"lane; {shape_b}. The gate said yes and nothing filled "
                f"-- check trade_execution (is it registered, enabled, "
                f"crashing?), then the book's buying power and route."
            )
            await self._raise_flow(
                key_b, severity="urgent",
                title=f"Trezo: approvals are dying at execution ({lane})",
                msg=msg)
            out.append(AgentMessage(
                agent=self.name, kind="error",
                payload={"event": "execution_starvation", "lane": lane,
                         "approves": approves, "executes": 0,
                         "kills": kills, "unaccounted": unaccounted_b,
                         "top_kill_reason": top,
                         "window_min": round(window_min, 1), "note": msg}))
        elif executes > 0:
            # NET2-REV-02 (as above): a fill is recovery; silence is not.
            self._open_alerts.discard(key_b)
        return out

    async def _raise_flow(self, key: tuple[str, str], *, severity: str,
                          title: str, msg: str) -> None:
        """Persist + webhook ONCE per (kind, lane) while it persists."""
        if key in self._open_alerts:
            return
        self._open_alerts.add(key)
        await self._persist_alert(kind=key[0], target=key[1],
                                  severity=severity, message=msg)
        try:
            from app.runtime.alerts import notify
            # NET2-REV-03: pass the severity through; it was pinned to
            # "urgent" so a fully-vetoed (warn) window pinged as red.
            await notify(title, msg, severity=severity,
                         key=f"{key[0]}:{key[1]}")
        except Exception:  # noqa: BLE001
            pass

    async def tick(self) -> list[AgentMessage]:
        # OPS RELAY -- EVERY TICK (Mike 2026-08-13). First version sat
        # inside the once-a-day janitor block, so the mailbox would have
        # been checked once per 24h: useless for "fix it while I sleep".
        # The whole point is a job queued now runs within one tick.
        # Whitelisted kinds only, never trading. Also pushes the server's
        # activity log back to Supabase so Nova can read it from anywhere.
        try:
            from app.runtime.settings import _supabase as _sb_relay
            _relay_cl = _sb_relay()
            if _relay_cl is not None:
                from app.runtime.ops_relay import drain_once, push_log_tail
                await drain_once(_relay_cl)
                await push_log_tail(_relay_cl)
        except Exception:  # noqa: BLE001
            pass
        # Route audit (2026-08-11): every tick, verify each book's
        # broker-routed ledger rows exist at that book's OWN broker.
        # Catches the mis-routed-stray pattern (7 found on 8/10-11) the
        # same cycle it happens instead of when a human notices. Fails
        # open; detection always on, autorepair behind its own flag.
        try:
            from app.brokers.route_guard import audit_routes
            # Findings are recorded as route_orphan activity lines inside
            # audit_routes itself -- greppable and Mike-visible. Nothing
            # to return here; a failed audit must never block the tick.
            await audit_routes()
        except Exception:  # noqa: BLE001
            pass
        out: list[AgentMessage] = []
        # Daily DB janitor (2026-07-07, Task #56 finally shipped): purge
        # agent_messages older than 48h once per day. The table regrew to
        # 266k rows and pinned the nano Supabase instance before the 7/7
        # manual purge -- this keeps it permanently small.
        try:
            global _JANITOR_DAY
            from datetime import date as _d
            from datetime import datetime as _dt
            from datetime import timedelta as _td
            from datetime import timezone as _tz
            _today = _d.today().isoformat()

            # MARKET BRIEFS (Mike 2026-08-12: "do it the right way --
            # everything self reliant"). Pre-market and pre-close reads
            # computed BY the engine. Weekdays only; once each per day;
            # ET approximated the same way is_market_hours does.
            #
            # AUDIT 2026-08-27: this block used to live INSIDE the
            # once-a-day janitor gate below. The gate trips when the
            # calendar flips -- 8 PM ET on a 24/7 engine -- and the
            # brief windows want 8:30 AM and 3:25 PM, so the two could
            # never coincide and the engine-side briefs had never fired
            # once. Same indentation failure as the 08-22 drain_once
            # bug, one function over. Now checked EVERY tick; the
            # _BRIEF_*_DAY latches already make it once-per-day.
            try:
                global _BRIEF_AM_DAY, _BRIEF_PM_DAY
                _bnow = _dt.now(_tz.utc)
                _bet_h = (_bnow.hour - 4) % 24
                _bet_m = _bnow.minute
                _bday = _bnow.date().isoformat()
                _bwk = _bnow.weekday() < 5
                if _bwk and (_BRIEF_AM_DAY != _bday or _BRIEF_PM_DAY != _bday):
                    from app.runtime.settings import _supabase as _bsb
                    _bcl = _bsb()
                    if _bcl is not None:
                        if (_BRIEF_AM_DAY != _bday
                                and (_bet_h == 8 and _bet_m >= 30
                                     or _bet_h == 9 and _bet_m <= 25)):
                            _BRIEF_AM_DAY = _bday
                            from app.knowledge.market_brief import build_brief
                            await build_brief(_bcl, "pre_market")
                        if (_BRIEF_PM_DAY != _bday
                                and _bet_h == 15 and _bet_m >= 25):
                            _BRIEF_PM_DAY = _bday
                            from app.knowledge.market_brief import build_brief
                            await build_brief(_bcl, "pre_close")
            except Exception:  # noqa: BLE001
                pass

            if _JANITOR_DAY != _today:
                _JANITOR_DAY = _today
                from app.runtime.settings import _supabase as _sb
                _cl = _sb()
                if _cl is not None:
                    _cut = (_dt.now(_tz.utc) - _td(hours=48)).isoformat()

                    def _purge():
                        return (_cl.table("agent_messages")
                                .delete().lt("created_at", _cut).execute())
                    import asyncio as _aio
                    await _aio.to_thread(_purge)
                    try:
                        from app.agents.activity_log import record as _arec
                        _arec("db_janitor", "SYSTEM",
                              reason="daily purge: agent_messages older "
                                     "than 48h removed",
                              extra={})
                    except Exception:  # noqa: BLE001
                        pass
                # Knowledge drop-folder sweep (Mike 2026-07-16): anything
                # dropped into C:\Trezo\Quantconnect (or the external-
                # research folder) joins the library within a day -- no
                # script run needed. The library reindexes itself when
                # the folder changes.
                try:
                    from app.knowledge.library import (
                        sweep_local_sources, sweep_report,
                    )
                    _swept = sweep_local_sources()
                    _srep = sweep_report()
                    if _swept:
                        from app.agents.activity_log import record as _krec
                        _krec("library_sweep", "SYSTEM",
                              reason=(f"{_swept} new/updated file(s) from "
                                      f"the drop-folders joined the "
                                      f"knowledge library"),
                              extra={})
                    # Say out loud what could NOT be read (Mike 2026-08-03).
                    # Screenshots and video are inert to the agents; silence
                    # let him assume they had been absorbed.
                    if _srep.get("unreadable_count"):
                        from app.agents.activity_log import record as _urec
                        _urec("library_unreadable", "SYSTEM",
                              reason=(f"{_srep['unreadable_count']} file(s) "
                                      f"in the drop-box cannot be read "
                                      f"(images/video/audio): "
                                      f"{', '.join(_srep['unreadable'][:5])}"
                                      f" - add a .md note describing them "
                                      f"and that text will be indexed"),
                              extra={"files": _srep.get("unreadable")})
                except Exception:  # noqa: BLE001
                    pass
                # DAILY DIGEST (Mike 2026-07-27: "why would it be a task
                # by you and not something the agents get done?"). The
                # engine runs 24/7; Nova's scheduled task only runs when
                # the desktop is open. So the AGENTS compute their own
                # day -- P&L by lane, profit factor, funnel, book state --
                # and write TREZO_DAILY_DIGEST.md. Nova/UI only present it.
                try:
                    from app.knowledge.daily_digest import build_digest
                    _eq = _cusd = 0.0
                    try:
                        from app.brokers.alpaca import (
                            get_account as _ga, alpaca_configured as _ac,
                        )
                        if _ac():
                            _acct = await _ga()
                            if _acct:
                                _eq = float(getattr(_acct, "equity", 0) or 0)
                                _cusd = float(getattr(
                                    _acct, "non_marginable_buying_power",
                                    0) or 0)
                    except Exception:  # noqa: BLE001
                        pass
                    _dg = await build_digest(_cl, equity=_eq,
                                             crypto_usd=_cusd)
                    from app.agents.activity_log import record as _drec
                    _drec("daily_digest", "SYSTEM",
                          reason=(f"{_dg.get('date')}: "
                                  f"${_dg.get('net_realized', 0):+.2f} "
                                  f"realized on {_dg.get('closed', 0)} "
                                  f"closes, PF {_dg.get('profit_factor')}, "
                                  f"{_dg.get('open_positions')} open"),
                          extra={"lanes": _dg.get("lanes"),
                                 "funnel": _dg.get("funnel")})
                    out.append(AgentMessage(
                        agent=self.name, kind="info",
                        payload={"event": "daily_digest", **{
                            k: _dg.get(k) for k in
                            ("date", "net_realized", "profit_factor",
                             "wins", "losses", "lanes", "open_positions",
                             "hit_floor_10", "alarm")}}))
                except Exception:  # noqa: BLE001
                    pass
                # RESEARCH HARVEST (Mike 2026-08-03): once a week the
                # agents go and read the open-access quant literature
                # themselves -- arXiv q-fin -- and file distilled,
                # fully-cited notes into the library. Extract and
                # attribute; never mirror the papers. Knowledge informs
                # the thesis, never the gates.
                try:
                    from datetime import date as _dr
                    if _dr.today().weekday() == 0:   # Monday
                        from app.knowledge.research_harvester import harvest
                        _rh = await harvest()
                        if _rh.get("stored"):
                            from app.agents.activity_log import record as _rrec
                            _rrec("research_harvest", "SYSTEM",
                                  reason=(f"read {_rh['checked']} new papers, "
                                          f"kept {_rh['stored']} relevant to "
                                          f"how Trezo trades: "
                                          f"{'; '.join(_rh['titles'][:3])}"),
                                  extra={"titles": _rh.get("titles")})
                            out.append(AgentMessage(
                                agent=self.name, kind="info",
                                payload={"event": "research_harvest",
                                         "checked": _rh["checked"],
                                         "stored": _rh["stored"],
                                         "titles": _rh["titles"][:5],
                                         "note": (
                                             f"The agents read "
                                             f"{_rh['checked']} new quant "
                                             f"papers and kept "
                                             f"{_rh['stored']}")}))
                except Exception:  # noqa: BLE001
                    pass
                # AGENT PROPOSALS (Mike 2026-07-27): the agents read their
                # own day -- vetoes, rejects, closed records -- and write
                # what they believe should CHANGE into
                # C:\Trezo\TREZO_AGENT_PROPOSALS.md. Evidence only; they
                # never self-apply a rule. Mike reads and decides.
                try:
                    from app.knowledge.proposal_engine import run_detectors
                    _pr = await run_detectors(_cl)
                    if _pr.get("filed"):
                        from app.agents.activity_log import record as _prec
                        _prec("agent_proposals", "SYSTEM",
                              reason=(f"{len(_pr['filed'])} rule-change "
                                      f"proposal(s) written from the day's "
                                      f"evidence: "
                                      f"{', '.join(_pr['filed'][:4])}"),
                              extra={"doc": _pr.get("doc")})
                        out.append(AgentMessage(
                            agent=self.name, kind="info",
                            payload={"event": "agent_proposals",
                                     "count": len(_pr["filed"]),
                                     "keys": _pr["filed"],
                                     "note": (
                                         f"The agents filed "
                                         f"{len(_pr['filed'])} proposed "
                                         f"rule change(s) from today's "
                                         f"evidence - see "
                                         f"TREZO_AGENT_PROPOSALS.md")}))
                except Exception:  # noqa: BLE001
                    pass
                # Sector Compass (2026-07-13, Mike): daily industry read --
                # 3-day movers every day, weekly (5d) view on Mondays, and
                # a monthly market update roughly every 21 days. Lands in
                # the activity log + agent memory so strategy planning has
                # a direction beyond the watchlist.
                try:
                    from app.agents.activity_log import record as _srec
                    from app.data.market_universe import sector_compass
                    _w = await sector_compass()

                    def _fmt(rows):
                        return ", ".join(
                            f"{s} {p:+.1f}%" for s, p in rows)
                    if _w.get("3d"):
                        _srec("sector_compass", "MARKET",
                              reason=("3-day industry movers -- leading: "
                                      f"{_fmt(_w['3d'][:3])} | lagging: "
                                      f"{_fmt(_w['3d'][-3:])}"),
                              extra={"window": "3d"})
                    _gen = (_w.get("generals") or [])[:5]
                    if _gen:
                        _srec("sector_compass", "MARKET",
                              reason=("generals of the leading sectors -- "
                                      + ", ".join(
                                          f"{g['sym']} {g['d1']:+.1f}% today"
                                          f" ({g['d3']:+.1f}% 3d)"
                                          for g in _gen)),
                              extra={"window": "generals"})
                    if _d.today().weekday() == 0 and _w.get("5d"):
                        _srec("sector_compass", "MARKET",
                              reason=("weekly industry read -- leading: "
                                      f"{_fmt(_w['5d'][:3])} | lagging: "
                                      f"{_fmt(_w['5d'][-3:])}"),
                              extra={"window": "5d"})
                    if _d.today().toordinal() % 21 == 0 and _w.get("21d"):
                        _srec("sector_compass", "MARKET",
                              reason=("monthly market update (21-day) -- "
                                      f"leading: {_fmt(_w['21d'][:3])} | "
                                      f"lagging: {_fmt(_w['21d'][-3:])}"),
                              extra={"window": "21d"})
                    try:
                        from app.memory.mem0_client import get_memory as _gmm
                        if _w.get("3d"):
                            _gmm().queue_note(
                                "ops_watchdog",
                                ("sector compass 3d: up "
                                 + _fmt(_w["3d"][:3]) + "; down "
                                 + _fmt(_w["3d"][-3:])),
                                ticker="MARKET")
                    except Exception:  # noqa: BLE001
                        pass
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001
            pass
        # Auto-clear stale advisories (Mike 2026-07-15: "on auto, this
        # popup should not linger -- it should go to a system log and be
        # held on the backend for audits"). Non-urgent exit-advisor
        # alerts older than 2h get acknowledged_at stamped hourly -- the
        # rows STAY in the table as the audit trail; only the screen
        # forgets them. Urgent alerts are never auto-cleared.
        try:
            global _ALERT_ACK_HOUR
            from datetime import datetime as _adt
            from datetime import timedelta as _atd
            from datetime import timezone as _atz
            _hr = _adt.now(_atz.utc).strftime("%Y-%m-%dT%H")
            if _ALERT_ACK_HOUR != _hr:
                _ALERT_ACK_HOUR = _hr
                from app.runtime.settings import _supabase as _asb
                _acl = _asb()
                if _acl is not None:
                    _cut2 = (_adt.now(_atz.utc)
                             - _atd(hours=2)).isoformat()

                    def _ack():
                        return (_acl.table("exit_advisor_alerts")
                                .update({"acknowledged_at": "now()"})
                                .is_("acknowledged_at", "null")
                                .neq("severity", "urgent")
                                .lt("raised_at", _cut2)
                                .execute())
                    import asyncio as _aio2
                    _res = await _aio2.to_thread(_ack)
                    _nacked = len(getattr(_res, "data", None) or [])
                    if _nacked:
                        try:
                            from app.agents.activity_log import record as _aar
                            _aar("alert_autoclear", "SYSTEM",
                                 reason=(f"{_nacked} stale non-urgent "
                                         f"advisories auto-cleared from the "
                                         f"screen (kept in the audit table)"),
                                 extra={})
                        except Exception:  # noqa: BLE001
                            pass
        except Exception:  # noqa: BLE001
            pass
        try:
            # Fixed 2026-06-11: this used to import _last_tick_at from
            # app.runtime.scheduler -- a name that NEVER existed. The
            # ImportError fired on every tick, so the watchdog (built
            # after the 6/3 silence incident!) was itself dead from the
            # day it shipped. Tick times live on the registry's
            # AgentState (state.last_tick_at, set by mark_ticked()).
            from app.runtime.registry import registry
        except Exception as e:  # noqa: BLE001
            return [AgentMessage(
                agent=self.name, kind="error",
                payload={"error": f"watchdog import failed: {str(e)[:200]}"},
            )]

        registered = {state.name: state for state in registry.all()}
        expected_names = {n for n, _ in EXPECTED_AGENTS}

        # --- Check 1: missing agents ---------------------------------
        missing = expected_names - set(registered.keys())
        for name in sorted(missing):
            key = ("missing_agent", name)
            if key in self._open_alerts:
                continue
            self._open_alerts.add(key)
            await self._persist_alert(
                kind="missing_agent",
                target=name,
                severity="urgent",
                message=(
                    f"Agent '{name}' is NOT in the runtime registry. "
                    f"Bootstrap likely failed silently. Check the "
                    f"start-agents.bat console window for an import "
                    f"traceback."
                ),
            )
            out.append(AgentMessage(
                agent=self.name, kind="error",
                payload={"event": "missing_agent", "target": name},
            ))

        # Clear stale dedupe entries when the condition resolves
        self._open_alerts = {
            k for k in self._open_alerts
            if not (k[0] == "missing_agent" and k[1] not in missing)
        }

        # --- Check 1b: is the DECISION PIPELINE producing anything? ---
        # Every other check here asks "is this agent ticking?" -- and
        # during the 8/27-8/31 outage every one of them said yes while
        # the platform traded nothing. This one asks whether decisions
        # come out the far end.
        try:
            out.extend(await self._check_flow())
        except Exception as e:  # noqa: BLE001
            logger.warning("ops_watchdog flow check failed: %s", e)

        # --- Check 2: scanner silence during market hours ------------
        market_open = _us_market_open()
        now = datetime.now(timezone.utc)
        for name, tolerance_min in EXPECTED_AGENTS:
            if name not in registered:
                continue  # missing-agent path handled it
            # Crypto scanner runs 24/7 - alert even outside US hours.
            this_market_open = True if name == "crypto_scanner" else market_open
            if not this_market_open:
                # Outside market hours, only alert on REALLY long silence.
                tolerance_min = max(tolerance_min, 1440)

            _st = registered.get(name)
            # REG-05: event-driven agents (risk_manager, trade_execution,
            # user_support) have tick_interval_seconds 0 and NEVER tick
            # by design -- they react on the bus. The exemption used to
            # sit inside the never-ticked branch only, so one forced tick
            # set last_tick_at and hours later they read as "stuck".
            # Skip Check 2 for them outright, whatever last_tick_at says.
            interval_s = getattr(getattr(_st, "impl", None),
                                 "tick_interval_seconds", 300)
            if interval_s is not None and interval_s <= 0:
                self._open_alerts.discard(("stuck_agent", name))
                self._open_alerts.discard(("never_ticked", name))
                continue
            last_dt = getattr(_st, "last_tick_at", None) if _st else None
            if last_dt is None:
                # Registered but has NEVER ticked. On a fresh boot that's
                # normal briefly; past 2x the agent's own interval it is
                # exactly the silent-failure case this watchdog exists
                # for (e.g. a tick that hangs or raises before returning).
                interval_s = interval_s or 300
                boot_grace_min = max((2 * interval_s) / 60.0, 10.0)
                uptime_min = (now - _BOOT_AT).total_seconds() / 60.0
                if uptime_min < boot_grace_min:
                    continue
                key = ("never_ticked", name)
                if key in self._open_alerts:
                    continue
                self._open_alerts.add(key)
                await self._persist_alert(
                    kind="stuck_agent",
                    target=name,
                    severity="urgent",
                    message=(
                        f"Agent '{name}' is registered but has NEVER "
                        f"ticked ({uptime_min:.0f} min since boot, "
                        f"interval {interval_s}s). Its tick is likely "
                        f"raising or hanging before completing. Check "
                        f"the agents console for 'agent.tick.failed' "
                        f"lines, or GET /agents for last_error."
                    ),
                )
                out.append(AgentMessage(
                    agent=self.name, kind="error",
                    payload={"event": "never_ticked", "target": name,
                             "uptime_min": round(uptime_min, 1)},
                ))
                continue
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            last_str = last_dt.isoformat()
            silence_min = (now - last_dt).total_seconds() / 60.0
            if silence_min < tolerance_min:
                # Healthy - clear any prior stuck alert for this agent
                self._open_alerts.discard(("stuck_agent", name))
                continue

            key = ("stuck_agent", name)
            if key in self._open_alerts:
                continue
            self._open_alerts.add(key)
            await self._persist_alert(
                kind="stuck_agent",
                target=name,
                severity="warn",
                message=(
                    f"Agent '{name}' has not ticked in "
                    f"{silence_min:.0f} minutes (tolerance "
                    f"{tolerance_min}). Last tick: {last_str}. "
                    f"Force a tick from /dashboard/agents or restart "
                    f"the service."
                ),
            )
            out.append(AgentMessage(
                agent=self.name, kind="info",
                payload={
                    "event": "stuck_agent",
                    "target": name,
                    "silence_min": round(silence_min, 1),
                },
            ))

        # --- Heartbeat info message -----------------------------------
        out.append(AgentMessage(
            agent=self.name, kind="info",
            payload={
                "event": "ops_heartbeat",
                "registered": sorted(registered.keys()),
                "expected": sorted(expected_names),
                "missing": sorted(missing),
                "stuck": sorted({n for kind, n in self._open_alerts
                                 if kind == "stuck_agent"}),
                "market_open": market_open,
            },
        ))

        return out

    async def _persist_alert(self, *, kind: str, target: str,
                             severity: str, message: str) -> None:
        """Insert an ops_health_alerts row. Best-effort - if the table
        doesn't exist yet (migration not applied), log and move on."""
        client = _supabase()
        if not client:
            return
        row = {
            "alert_kind": kind,
            "target_name": target,
            "severity": severity,
            "message": message,
            "raised_at": datetime.now(timezone.utc).isoformat(),
        }

        def _sync_insert():
            return client.table("ops_health_alerts").insert(row).execute()
        try:
            await asyncio.to_thread(_sync_insert)
        except Exception as e:  # noqa: BLE001
            logger.warning("ops_watchdog alert persist failed: %s", e)
