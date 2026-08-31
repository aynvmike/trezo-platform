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

  2. For each registered agent, checks `last_tick_at` (or
     last-message-seen as fallback). If a scanner has been silent
     for more than its tick interval times a tolerance multiplier
     during US market hours, raise an alert.

  3. Persists alerts to the new `ops_health_alerts` table (RLS off
     - this is platform-level monitoring, not per-user). The UI
     surfaces these as a "System health" panel on the Trading page.

  4. When a scanner is stuck, can optionally force-tick it via the
     internal `_tick_agent` helper. Gated by `OPS_AUTO_TICK_STUCK`
     setting so Mike can choose between alert-only and auto-recover.

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
    ("risk_manager", 240),        # event-driven, may sit quiet legitimately
    ("trade_execution", 240),     # event-driven downstream of risk_manager
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
    ("user_support", 1440),       # cold-path agent
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
        # APPROVAL STARVATION counters (2026-08-31). See _check_flow().
        self._flow: dict[str, float] = {
            "signals": 0, "approves": 0, "vetoes": 0,
            "handler_fails": 0, "since": _time.time(),
        }

    async def on_message(self, message: AgentMessage) -> list[AgentMessage]:
        # Count the shape of the decision pipeline. Deliberately free:
        # no I/O, no awaits, just tallies read by _check_flow() on the
        # 5-minute tick. This is the sensor for the outage that ran from
        # 8/27 to 8/31 -- signals firing, nothing approved, and the only
        # visible messages were vetoes from checks upstream of the crash.
        try:
            k = message.kind
            if k == "signal":
                self._flow["signals"] += 1
            elif k == "approve":
                self._flow["approves"] += 1
            elif k == "veto":
                self._flow["vetoes"] += 1
            elif k == "error" and isinstance(message.payload, dict) and (
                    message.payload.get("event") == "handler_failed"):
                self._flow["handler_fails"] += 1
        except Exception:  # noqa: BLE001
            pass
        return []

    async def _check_flow(self) -> list[AgentMessage]:
        """Alarm when signals go in and NOTHING comes out.

        THE CASE THIS EXISTS FOR (2026-08-31): risk_manager.on_message
        raised on every signal carrying a real direction. The router
        swallowed it, so there was no error to find -- the platform
        simply approved nothing for four trading days while the log
        looked merely quiet. Every other check here asks "is this agent
        ticking?" and every one of them said yes.

        So this check asks the question the outage would have failed:
        did anything get APPROVED? A window with plenty of signals, zero
        approvals and no explanatory vetoes is not a slow tape -- the
        pipeline is broken somewhere between the scanners and execution.

        Thresholds are deliberately dull: market hours only, at least
        MIN_SIGNALS observed, and the window must be at least
        FLOW_WINDOW_MIN long, so a quiet morning cannot cry wolf.
        """
        out: list[AgentMessage] = []
        f = self._flow
        window_min = (_time.time() - f["since"]) / 60.0
        if window_min < FLOW_WINDOW_MIN:
            return out
        # Reset the window whatever we decide, so one bad window does not
        # poison the next one.
        signals, approves = int(f["signals"]), int(f["approves"])
        vetoes, hfails = int(f["vetoes"]), int(f["handler_fails"])
        self._flow = {"signals": 0, "approves": 0, "vetoes": 0,
                      "handler_fails": 0, "since": _time.time()}

        if not _us_market_open():
            return out
        if signals < FLOW_MIN_SIGNALS:
            return out                      # too thin to conclude anything
        if approves > 0:
            self._open_alerts.discard(("approval_starvation", "pipeline"))
            return out

        # Zero approvals on real signal flow. Say which shape it is:
        # accounted-for (every signal has a veto) vs UNACCOUNTED, which
        # is the dangerous one -- signals going in and nothing at all
        # coming out is a crash, not a decision.
        unaccounted = max(0, signals - vetoes)
        shape = (f"{vetoes} veto(es) explain them"
                 if unaccounted == 0 else
                 f"{unaccounted} of them produced NO verdict at all -- "
                 f"not an approval, not a veto")
        msg = (
            f"APPROVAL STARVATION: {signals} signal(s) in "
            f"{window_min:.0f} min of market hours produced ZERO "
            f"approvals; {shape}"
            + (f"; {hfails} handler crash(es) reported" if hfails else "")
            + ". A silent pipeline is what the 8/27-8/31 outage looked "
              "like: every agent ticking, nothing traded. Check "
              "risk_manager first, then trade_execution."
        )
        key = ("approval_starvation", "pipeline")
        if key not in self._open_alerts:
            self._open_alerts.add(key)
            await self._persist_alert(
                kind="approval_starvation", target="pipeline",
                severity="urgent" if unaccounted else "warn", message=msg)
            try:
                from app.runtime.alerts import notify
                await notify("Trezo: nothing is being approved", msg,
                             severity="urgent", key="approval_starvation")
            except Exception:  # noqa: BLE001
                pass
        out.append(AgentMessage(
            agent=self.name, kind="error",
            payload={"event": "approval_starvation", "signals": signals,
                     "approves": 0, "vetoes": vetoes,
                     "unaccounted": unaccounted,
                     "handler_failures": hfails,
                     "window_min": round(window_min, 1), "note": msg}))
        return out

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
            last_dt = getattr(_st, "last_tick_at", None) if _st else None
            if last_dt is None:
                # Registered but has NEVER ticked. On a fresh boot that's
                # normal briefly; past 2x the agent's own interval it is
                # exactly the silent-failure case this watchdog exists
                # for (e.g. a tick that hangs or raises before returning).
                interval_s = getattr(getattr(_st, "impl", None),
                                     "tick_interval_seconds", 300)
                if interval_s is not None and interval_s <= 0:
                    # Event-driven agents (risk_manager, trade_execution,
                    # user_support) have interval 0 and NEVER tick by
                    # design -- they react on the bus. 2026-06-12: these
                    # false-alarmed as never_ticked all morning.
                    continue
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
