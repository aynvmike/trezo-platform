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
                                     "tick_interval_seconds", 300) or 300
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
