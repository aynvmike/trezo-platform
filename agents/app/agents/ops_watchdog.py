"""Operations Watchdog - 21st agent. The supervisor.

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


_JANITOR_DAY = ""   # daily agent_messages purge marker (2026-07-07)
_ALERT_ACK_HOUR = ""  # hourly stale-advisory auto-ack marker (2026-07-15)


class OpsWatchdogAgent(Agent):
    """The 21st agent. Supervisor / health monitor."""

    name = "ops_watchdog"
    tick_interval_seconds = 300  # every 5 minutes

    def __init__(self) -> None:
        # In-memory dedupe: don't re-alert the same condition every tick
        # while it persists. Keyed by (alert_kind, target_name).
        self._open_alerts: set[tuple[str, str]] = set()

    async def on_message(self, message: AgentMessage) -> list[AgentMessage]:
        return []

    async def tick(self) -> list[AgentMessage]:
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
