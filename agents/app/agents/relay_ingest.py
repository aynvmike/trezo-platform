"""Relay Ingest -- Nova's briefings become the engine's context.

WHY (Mike, 2026-08-21): the skills Nova runs for Mike -- market-report,
market-movers-report, trezo-daily-wrap, trezo-midday-snapshot,
trezo-server-sentinel -- already produce a structured read of the tape,
the book and the box. Until now only Mike read it. Each skill now ends
its run by posting one row to `relay_briefings` (migration 0056), and
this agent drains those rows and files them where the other agents can
see them.

What "files them" means -- CONTEXT ONLY, by decision (8/21):

  1. VALIDATE the payload against the schema for its kind. A briefing
     that does not fit is marked `rejected` with the exact reason, the
     rejection goes to the activity log, and an `info` message with
     severity=warning crosses the bus. It is never dropped quietly.
  2. SEPARATE by kind into the right memory scope, so a scanner asking
     "what's the regime" is not wading through server health notes:
        market_context -> scope 'relay:market'
        daily_wrap     -> scope 'relay:analytics'
        health         -> scope 'relay:health'
     plus ONE reinforced entry per kind in the 'shared' pool under a
     stable topic ('relay.market_context.latest' ...), so the newest
     brief is what every agent's default `recall()` surfaces.
  3. ANNOUNCE with an `info` bus message carrying the summary.

What it must NOT do, and has no code path to do: emit `event` messages
(Adaptive Scope acts on those), change scope/posture/sizing, touch
settings, queue ops jobs, or place orders. If Mike later wants briefings
to carry soft signals, that is a new, separate handler -- not a tweak to
this one.

Schema and RLS: db/migrations/0056_relay_briefings.sql.
Posting side: ops/relay.py brief / briefs.
Guards: agents/tests/test_relay_ingest.py.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from app.config import get_settings

from .base import Agent, AgentMessage


logger = logging.getLogger(__name__)

# One batch per tick. A flood of briefs cannot starve the scheduler.
MAX_PER_TICK = 10

# A brief older than this is a brief about a world that no longer
# exists. Refuse it loudly rather than let a stale regime sit in memory
# wearing today's date.
MAX_AGE = timedelta(hours=48)

# Keep memory rows bounded; the full payload stays in relay_briefings.
SUMMARY_MAX = 1200

# Where each kind is filed.  kind -> (memory scope, shared topic)
ROUTES: dict[str, tuple[str, str]] = {
    "market_context": ("relay:market",    "relay.market_context.latest"),
    "daily_wrap":     ("relay:analytics", "relay.daily_wrap.latest"),
    "health":         ("relay:health",    "relay.health.latest"),
}

# Per-kind schema: required field -> accepted python types / choices.
# Kept deliberately small. Optional fields pass through untouched.
_NUM = (int, float)
SCHEMAS: dict[str, dict[str, Any]] = {
    "market_context": {
        "as_of":   str,
        "slot":    {"pre-market", "open", "midday", "pre-close", "post-close", "intraday"},
        "regime":  {"risk_on", "risk_off", "mixed", "unknown"},
        "indices": dict,        # {"SPY": {"pct": -0.4}, ...} or {"SPY": -0.4}
        "summary": str,
    },
    "daily_wrap": {
        "as_of":            str,
        "trade_date":       str,
        "realized_pnl_usd": _NUM,
        "target_pnl_usd":   _NUM,
        "open_positions":   int,
        "lanes":            dict,   # {"crypto": {"wins": 3, "losses": 1, "pnl": 12.4}, ...}
        "summary":          str,
    },
    "health": {
        "as_of":    str,
        "verdict":  {"healthy", "degraded", "down", "unknown"},
        "findings": list,
        "summary":  str,
    },
}


class BriefingRejected(ValueError):
    """The brief does not fit its schema. The message IS the reason."""


def _parse_ts(value: str) -> datetime:
    t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t


def validate(kind: str, payload: Any, *, now: datetime | None = None) -> dict:
    """Return the payload if it fits the schema for `kind`; else raise
    BriefingRejected with a reason a human can act on."""
    if kind not in SCHEMAS:
        raise BriefingRejected(f"unknown kind '{kind}' (allowed: {sorted(SCHEMAS)})")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except Exception as e:  # noqa: BLE001
            raise BriefingRejected(f"payload is not JSON: {e}") from None
    if not isinstance(payload, dict):
        raise BriefingRejected(f"payload must be an object, got {type(payload).__name__}")

    missing = [k for k in SCHEMAS[kind] if k not in payload]
    if missing:
        raise BriefingRejected(f"missing required field(s): {', '.join(missing)}")

    for field, rule in SCHEMAS[kind].items():
        val = payload[field]
        if isinstance(rule, set):
            if val not in rule:
                raise BriefingRejected(
                    f"{field}={val!r} not in {sorted(rule)}")
        elif rule is int:
            if isinstance(val, bool) or not isinstance(val, int):
                raise BriefingRejected(f"{field} must be an integer, got {val!r}")
        elif not isinstance(val, rule):
            want = getattr(rule, "__name__", None) or "/".join(r.__name__ for r in rule)
            raise BriefingRejected(f"{field} must be {want}, got {type(val).__name__}")

    if not str(payload["summary"]).strip():
        raise BriefingRejected("summary is empty")

    try:
        as_of = _parse_ts(payload["as_of"])
    except Exception:  # noqa: BLE001
        raise BriefingRejected(f"as_of={payload['as_of']!r} is not an ISO timestamp") from None
    now = now or datetime.now(timezone.utc)
    if now - as_of > MAX_AGE:
        raise BriefingRejected(
            f"stale: as_of is {(now - as_of).total_seconds() / 3600:.0f}h old (max {MAX_AGE.total_seconds() / 3600:.0f}h)")
    if as_of - now > timedelta(hours=1):
        raise BriefingRejected("as_of is in the future")
    return payload


def summarize(kind: str, payload: dict) -> str:
    """The compact line that goes into agent memory. Full payload stays
    in the table; memory gets what an agent needs at a glance."""
    head = {"market_context": f"[{payload.get('slot')}] regime={payload.get('regime')}",
            "daily_wrap": (f"[{payload.get('trade_date')}] realized=${payload.get('realized_pnl_usd')} "
                           f"target=${payload.get('target_pnl_usd')} open={payload.get('open_positions')}"),
            "health": f"[{payload.get('source', 'nova')}] verdict={payload.get('verdict')}",
            }[kind]
    body = str(payload["summary"]).strip()
    return f"{head} as_of={payload['as_of']} :: {body}"[:SUMMARY_MAX]


def _supabase():
    s = get_settings()
    if not s.supabase_url or not s.supabase_service_role_key:
        return None
    try:
        from supabase import create_client
        return create_client(s.supabase_url, s.supabase_service_role_key)
    except Exception:  # noqa: BLE001
        return None


def _record(event: str, reason: str, ticker: str = "") -> None:
    try:
        from app.agents.activity_log import record
        record("relay_ingest", ticker or event, reason=reason[:280], extra={"event": event})
    except Exception:  # noqa: BLE001
        pass


class RelayIngestAgent(Agent):
    """Drains relay_briefings into agent memory. Context only."""

    name = "relay_ingest"
    tick_interval_seconds = 300

    def __init__(self) -> None:
        self._client = None
        self._client_tried = False

    def _cl(self):
        if not self._client_tried:
            self._client_tried = True
            self._client = _supabase()
        return self._client

    # ---- persistence --------------------------------------------------

    async def _fetch_new(self) -> list[dict]:
        cl = self._cl()
        if cl is None:
            return []

        def _q():
            return (cl.table("relay_briefings").select("*")
                    .eq("status", "new").order("created_at")
                    .limit(MAX_PER_TICK).execute())
        return (await asyncio.to_thread(_q)).data or []

    async def _mark(self, row_id: str, status: str, result: str) -> None:
        cl = self._cl()
        if cl is None:
            return

        def _u():
            return (cl.table("relay_briefings").update({
                "status": status, "result": result[:4000],
                "ingested_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", row_id).execute())
        await asyncio.to_thread(_u)

    # ---- the work -------------------------------------------------------

    async def ingest(self, row: dict) -> AgentMessage:
        """Validate, separate, file, announce. Returns the bus message.
        Pure enough to unit-test with a stub `remember`."""
        kind = str(row.get("kind"))
        source = str(row.get("source") or "unknown")
        rid = str(row.get("id"))
        try:
            payload = validate(kind, row.get("payload"))
        except BriefingRejected as e:
            reason = f"rejected {kind} from {source}: {e}"
            await self._mark(rid, "rejected", reason)
            _record("RELAY_BRIEF_REJECTED", reason)
            logger.warning("relay_ingest.rejected id=%s %s", rid, reason)
            return AgentMessage(agent=self.name, kind="info", payload={
                "note": reason, "severity": "warning",
                "briefing_id": rid, "source": source, "brief_kind": kind,
            })

        scope, shared_topic = ROUTES[kind]
        line = summarize(kind, payload)
        stamp = str(payload.get("slot") or payload.get("trade_date") or payload["as_of"][:10])

        ok_hist = await self.remember(f"{kind}:{payload['as_of'][:10]}:{stamp}", line,
                                      scope=scope, category=kind, weight_delta=0.0)
        ok_shared = await self.remember(shared_topic, line,
                                        scope="shared", category=kind, weight_delta=1.0)
        filed = ok_hist and ok_shared
        result = (f"ingested {kind} from {source} -> memory scope {scope} + shared/{shared_topic}"
                  + ("" if filed else " (memory write FAILED -- brief recorded here only)"))
        await self._mark(rid, "ingested", result)
        _record("RELAY_BRIEF_INGESTED", result)
        return AgentMessage(agent=self.name, kind="info", confidence=1.0 if filed else 0.3,
                            payload={
                                "note": line, "briefing_id": rid, "source": source,
                                "brief_kind": kind, "scope": scope, "memory_ok": filed,
                                "severity": "info" if filed else "warning",
                            })

    async def tick(self) -> list[AgentMessage]:
        try:
            rows = await self._fetch_new()
        except Exception as e:  # noqa: BLE001
            _record("RELAY_BRIEF_FETCH_FAILED", str(e))
            return [AgentMessage(agent=self.name, kind="error",
                                 payload={"error": f"relay_briefings read failed: {e}"})]
        out: list[AgentMessage] = []
        for row in rows:
            try:
                out.append(await self.ingest(row))
            except Exception as e:  # noqa: BLE001
                # One bad row must not poison the batch -- but it must
                # not hide either.
                rid = str(row.get("id"))
                try:
                    await self._mark(rid, "rejected", f"ingest crashed: {e}")
                except Exception:  # noqa: BLE001
                    pass
                _record("RELAY_BRIEF_CRASHED", f"{rid}: {e}")
                out.append(AgentMessage(agent=self.name, kind="error",
                                        payload={"briefing_id": rid, "error": str(e)}))
        return out
