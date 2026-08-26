"""Market Desk -- turns Nova's market reports into one view every lane reads.

WHY THIS EXISTS (2026-08-25, Mike: "I want to have an agent that can go
through the reports and can process for each agent so that we can stay
on top of the market. We have to get this working properly.")

The pipeline before tonight: the twice-daily market reports never posted
briefings at all (the scheduled prompts predated the relay step -- fixed
on the scheduler side the same night), relay_ingest filed what little
arrived into memory, and nothing read it back except the same-day
options lane's regime check. A mailbox, a filing clerk, and almost no
recipients.

This agent is the recipient. Every 5 minutes it looks for the newest
VALID market_context briefing, digests the full payload -- regime,
indices, vix, breadth, movers, catalysts -- into one structured
MarketView, and serves it to every consumer through current_market_view()
in THIS module. Writer and readers share a file on purpose: the ex-date
guard taught us what happens when a format's producer and consumer are
allowed to drift apart in silence.

WHAT IT NEVER DOES. The desk holds no opinions of its own and moves no
levers. It cannot change scope, posture, sizing, or orders, and every
consumer is required to treat a missing or stale view as "no opinion"
-- an absent report leaves every lane exactly as it was before this
agent existed. Consumers may only TIGHTEN on what the desk serves
(higher bars, fewer slots, deferrals), never loosen. The report can
take risk off the table; it can never put risk on.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from .base import Agent, AgentMessage

# A view older than this is history, not context. One trading session.
VIEW_MAX_AGE_H = 24.0

VALID_REGIMES = ("risk_on", "risk_off", "mixed", "unknown")


@dataclass
class MarketView:
    """One report, digested. Everything optional except provenance --
    a consumer must always be able to say WHERE its context came from."""
    as_of: str
    slot: str
    source: str
    regime: str = "unknown"
    indices: dict = field(default_factory=dict)     # SPY/QQQ/DIA/IWM pct
    vix: Optional[float] = None
    breadth: str = ""
    movers_up: list = field(default_factory=list)
    movers_down: list = field(default_factory=list)
    catalysts: list = field(default_factory=list)
    summary: str = ""

    def age_hours(self, now: Optional[datetime] = None) -> Optional[float]:
        try:
            stamp = datetime.fromisoformat(
                str(self.as_of).replace("Z", "+00:00"))
            now = now or datetime.now(timezone.utc)
            return (now - stamp).total_seconds() / 3600.0
        except Exception:  # noqa: BLE001
            return None

    def fresh(self) -> bool:
        age = self.age_hours()
        return age is not None and 0 <= age <= VIEW_MAX_AGE_H


def build_view(payload: dict, source: str = "") -> Optional[MarketView]:
    """A validated MarketView from a raw market_context payload, or None.

    Tolerant of missing optional fields, strict about the ones that
    carry meaning: an unrecognized regime becomes "unknown" rather than
    passing through (the engine already rejected regime='bananas' once
    at ingest; this is the same wall on the consumer side), and tickers
    are uppercased so set membership tests cannot miss on case.
    """
    if not isinstance(payload, dict):
        return None
    as_of = str(payload.get("as_of") or "").strip()
    if not as_of:
        return None
    regime = str(payload.get("regime") or "unknown").strip().lower()
    if regime not in VALID_REGIMES:
        regime = "unknown"

    def _syms(key: str) -> list:
        out = []
        for s in (payload.get(key) or []):
            t = str(s or "").upper().strip()
            if t and t not in out:
                out.append(t)
        return out[:12]

    indices = {}
    for k, v in (payload.get("indices") or {}).items():
        try:
            indices[str(k).upper()] = float(v)
        except (TypeError, ValueError):
            continue
    vix = None
    try:
        if payload.get("vix") is not None:
            vix = float(payload["vix"])
    except (TypeError, ValueError):
        vix = None
    return MarketView(
        as_of=as_of,
        slot=str(payload.get("slot") or ""),
        source=source or str(payload.get("source") or ""),
        regime=regime,
        indices=indices,
        vix=vix,
        breadth=str(payload.get("breadth") or "")[:200],
        movers_up=_syms("movers_up"),
        movers_down=_syms("movers_down"),
        catalysts=[str(c)[:120] for c in (payload.get("catalysts") or [])][:8],
        summary=str(payload.get("summary") or "")[:600],
    )


# The one place the current view lives. Process-local on purpose: the
# desk re-reads the table every tick, so a restart rebuilds this within
# five minutes and nothing stale survives a deploy.
_current: Optional[MarketView] = None
_current_at: float = 0.0


def current_market_view() -> Optional[MarketView]:
    """THE reader every consumer uses. Fresh view or None -- never a
    stale one, so no consumer needs its own staleness arithmetic."""
    v = _current
    if v is not None and v.fresh():
        return v
    return None


class MarketDeskAgent(Agent):
    name = "market_desk"
    tick_interval_seconds = 300

    _last_seen_as_of: str = ""

    async def tick(self) -> list[AgentMessage]:
        global _current, _current_at
        row = await self._newest_briefing()
        if not row:
            return []
        view = build_view(row.get("payload") or {},
                          source=str(row.get("source") or ""))
        if view is None or not view.fresh():
            return []
        if view.as_of == self._last_seen_as_of:
            return []                     # same report; nothing new to say
        self._last_seen_as_of = view.as_of
        _current = view
        _current_at = time.time()

        # Say what was read, once per report, in the feed -- so "are the
        # agents reviewing the reports?" has a visible receipt.
        try:
            from app.agents.activity_log import record as _arec
            _arec("market_view", "MARKET",
                  reason=(f"[{view.slot}] regime={view.regime} "
                          f"vix={view.vix} up={','.join(view.movers_up[:4])} "
                          f"down={','.join(view.movers_down[:4])} :: "
                          f"{view.summary[:160]}"))
        except Exception:  # noqa: BLE001
            pass
        return [AgentMessage(
            agent=self.name, kind="info",
            payload={
                "ticker": "MARKET", "event": "market_view",
                "slot": view.slot, "regime": view.regime,
                "vix": view.vix, "movers_up": view.movers_up,
                "movers_down": view.movers_down,
                "note": f"market view updated from {view.source or 'report'}"
                        f" [{view.slot}]: regime={view.regime}",
            })]

    async def _newest_briefing(self) -> Optional[dict]:
        """Newest ingested market_context row, straight from the table.

        The FULL payload lives only in relay_briefings; agent memory
        holds a one-line summary. The desk wants the movers and
        catalysts, so it reads the table. Fail-open: any error is an
        empty read, and an empty read changes nothing.
        """
        try:
            import asyncio
            from app.config import get_settings
            s = get_settings()
            if not s.supabase_url or not s.supabase_service_role_key:
                return None
            from supabase import create_client
            cl = create_client(s.supabase_url, s.supabase_service_role_key)

            def _q():
                return (cl.table("relay_briefings")
                        .select("payload, source, created_at")
                        .eq("kind", "market_context")
                        .eq("status", "ingested")
                        .order("created_at", desc=True)
                        .limit(1).execute())
            rows = (await asyncio.to_thread(_q)).data or []
            return rows[0] if rows else None
        except Exception:  # noqa: BLE001
            return None
