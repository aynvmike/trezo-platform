"""
Trezo's Mem0 client - the shared brain across all agents.

Why this exists
---------------
The Trezo agents (Risk Manager, Exit Advisor, Cycle Awareness, etc.)
each make discrete decisions every tick. Without shared memory, every
day starts from zero: they don't remember which signals worked, which
vetoes were wrong, which regimes mattered.

Mem0 gives them a queryable, semantic shared store. Each agent:
  1. Logs its decision + reasoning via memory.log_decision()
  2. Logs the outcome (once the trade closes) via memory.log_outcome()
  3. BEFORE its next decision, queries memory.recall_similar() for
     past situations like the one it's about to act on.

This is the outcome-aware learning loop. It doesn't change agent
logic - the agent still scores, vetoes, alerts. What changes is the
agent can NOW say "in 11 of the last 14 times this pattern hit,
the trade lost money" and weight accordingly.

Design notes
------------
- Singleton via get_memory() - all agents share one client per process.
- DEGRADES GRACEFULLY: if MEM0_API_KEY is missing or the Mem0 call
  fails, the agents keep working. Memory is a force multiplier, not
  a hard dependency.
- user_id is fixed to "trezo" per project. When Mike spins up the next
  project, it gets its own user_id and stays isolated.
- agent_id is the source of the memory (e.g., "risk_manager").
- metadata carries structured fields (ticker, tcs, side, regime) so
  Mem0 can filter as well as semantic-search.

Wired by Nova for Mike on 2026-06-01.
"""

from __future__ import annotations

import logging
import time as _time

# 2026-06-11: Mem0 ADD quota hit 10000/10000 (resets 2026-07-01) because
# every routine veto was logged. When the API answers 429/quota, pause
# WRITES for a while instead of hammering + spamming warnings. Reads
# (search) are unaffected by the ADD quota and keep working.
_WRITE_PAUSE_SECONDS = 6 * 3600.0
_writes_paused_until: float = 0.0

# ---------------------------------------------------------------------------
# Usage budget (2026-06-12). Mike upgraded the Mem0 plan after the first
# 10k ADD quota burned in <2 weeks -- almost entirely routine-veto noise,
# while only ~6 recalls had ever run. Policy: adds are budgeted per DAY
# and per ISO WEEK; retrievals get a high daily ceiling so the agents can
# ALWAYS consult memory before decisions. Counters persist to a JSON file
# next to this module so the daily restarts don't reset spend. Limits are
# tunable in agents/.env (mem0_max_adds_per_day, mem0_max_adds_per_week,
# mem0_max_searches_per_day -- read via Settings, NOT os.getenv, because
# pydantic-settings does not export .env values to the process env).
# ---------------------------------------------------------------------------
import json as _json
import os as _os
import threading as _threading
from datetime import datetime as _dt, timezone as _tz

_BUDGET_FILE = _os.path.join(_os.path.dirname(__file__), ".usage_budget.json")
_BUDGET_LOCK = _threading.Lock()
_throttle_logged_at: dict[str, float] = {}


def _budget_limits() -> tuple[int, int, int]:
    try:
        from app.config import get_settings
        s = get_settings()
        return (int(s.mem0_max_adds_per_day),
                int(s.mem0_max_adds_per_week),
                int(s.mem0_max_searches_per_day))
    except Exception:  # noqa: BLE001
        return (400, 2500, 2000)


def _budget_load() -> dict:
    try:
        with open(_BUDGET_FILE, encoding="utf-8") as f:
            b = _json.load(f)
        if isinstance(b, dict):
            return b
    except Exception:  # noqa: BLE001
        pass
    return {}


def _budget_save(b: dict) -> None:
    try:
        tmp = _BUDGET_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            _json.dump(b, f)
        _os.replace(tmp, _BUDGET_FILE)
    except Exception:  # noqa: BLE001
        pass


def _budget_roll(b: dict) -> dict:
    now = _dt.now(_tz.utc)
    day = now.strftime("%Y-%m-%d")
    iso = now.isocalendar()
    week = f"{iso.year}-W{iso.week:02d}"
    if b.get("day") != day:
        b["day"] = day
        b["adds_today"] = 0
        b["searches_today"] = 0
    if b.get("week") != week:
        b["week"] = week
        b["adds_week"] = 0
    return b


def _budget_try_spend(kind: str) -> bool:
    """Atomically check + spend one unit of 'add' or 'search' budget.
    False = cap exhausted, caller must skip the API call. Never raises;
    bookkeeping failure must never block the memory layer."""
    max_day, max_week, max_search = _budget_limits()
    try:
        with _BUDGET_LOCK:
            b = _budget_roll(_budget_load())
            if kind == "add":
                if (b.get("adds_today", 0) >= max_day
                        or b.get("adds_week", 0) >= max_week):
                    return False
                b["adds_today"] = b.get("adds_today", 0) + 1
                b["adds_week"] = b.get("adds_week", 0) + 1
            else:
                if b.get("searches_today", 0) >= max_search:
                    return False
                b["searches_today"] = b.get("searches_today", 0) + 1
            _budget_save(b)
            return True
    except Exception:  # noqa: BLE001
        return True


def _budget_throttle_log(kind: str) -> None:
    """Warn about an exhausted budget at most once per hour per kind."""
    now = _time.time()
    if now - _throttle_logged_at.get(kind, 0.0) >= 3600.0:
        _throttle_logged_at[kind] = now
        max_day, max_week, max_search = _budget_limits()
        logger.warning(
            "Mem0 %s budget exhausted (limits: %d adds/day, %d adds/week, "
            "%d searches/day) - skipping until the window rolls. Tune in "
            "agents/.env.", kind, max_day, max_week, max_search,
        )


def normalize_tags(metadata: dict) -> dict:
    """Tagging standard (Mike 2026-06-12: 'some of the memory tags are
    blank and we can benefit from having a system'). Every memory gets:
      - the four required keys filled (kind/agent/action/ticker;
        missing -> 'unknown', never blank),
      - strategy defaulted to 'unknown',
      - a flat lowercase `tags` list built from the above so dashboard
        filtering and future recall have ONE consistent vocabulary.
    Never raises; returns the enriched dict."""
    try:
        md = dict(metadata or {})
        for k in ("kind", "agent", "action", "ticker"):
            v = str(md.get(k) or "").strip()
            md[k] = v if v else "unknown"
        if not str(md.get("strategy") or "").strip():
            md["strategy"] = "unknown"
        tags = []
        for k in ("kind", "agent", "action", "ticker", "strategy"):
            v = str(md.get(k, "")).strip().lower()
            if v and v != "unknown" and v not in tags:
                tags.append(v)
        md["tags"] = tags
        return md
    except Exception:  # noqa: BLE001
        return dict(metadata or {})


def budget_status() -> dict:
    """Current spend vs limits. Surfaced via TrezoMemory.health()."""
    max_day, max_week, max_search = _budget_limits()
    with _BUDGET_LOCK:
        b = _budget_roll(_budget_load())
    return {
        "adds_today": b.get("adds_today", 0),
        "adds_per_day_limit": max_day,
        "adds_week": b.get("adds_week", 0),
        "adds_per_week_limit": max_week,
        "searches_today": b.get("searches_today", 0),
        "searches_per_day_limit": max_search,
    }


def _writes_paused() -> bool:
    return _time.time() < _writes_paused_until


def _maybe_pause_writes(err: Exception) -> None:
    global _writes_paused_until
    s = str(err)
    if "429" in s or "quota" in s.lower():
        _writes_paused_until = _time.time() + _WRITE_PAUSE_SECONDS
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Trezo's organization ID inside Mem0.
TREZO_USER_ID = "trezo"

# Default top-K for similarity search. Small because we want to keep
# the context the agents see tight and high-signal.
DEFAULT_RECALL_LIMIT = 5


@dataclass
class AgentDecision:
    """
    Structured representation of an agent decision worth remembering.

    Use this any time an agent makes a call that future-agent would
    benefit from knowing about: signal approvals, vetoes, exit alerts,
    regime calls, strategy selections.
    """

    agent: str  # which agent made the decision (e.g., 'risk_manager')
    action: str  # what was decided (e.g., 'veto', 'approve', 'alert')
    ticker: str  # the symbol involved (or 'market' for regime calls)
    reasoning: str  # plain-English why (this is what Mem0 indexes)
    metadata: dict[str, Any] = field(default_factory=dict)  # tcs, side, etc.
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class TradeOutcome:
    """
    Structured representation of a trade outcome - logged AFTER the
    trade closes. This is what closes the learning loop: agents can
    now correlate their decisions with realized P&L.
    """

    ticker: str
    side: str  # 'long' or 'short'
    entry_price: float
    exit_price: float
    realized_pnl_usd: float
    holding_days: int
    exit_reason: str  # 'target', 'stop', 'manual', 'partial', etc.
    strategy: str  # which strategy fired the signal
    related_decisions: list[str] = field(default_factory=list)  # memory IDs
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


class TrezoMemory:
    """
    Thin, safe wrapper around the Mem0 SDK.

    All public methods are designed to NEVER raise to the calling
    agent - if Mem0 is misconfigured or unreachable, the methods
    log a warning and return a benign default. This is by design:
    memory failure should never break a trading decision.
    """

    def __init__(self, api_key: Optional[str] = None, user_id: str = TREZO_USER_ID):
        self.user_id = user_id
        # Resolution order: explicit api_key arg -> agents Settings (.env
        # via pydantic-settings, which is how every other Trezo agent
        # reads config) -> os.environ fallback for non-agent callers.
        # NOTE: os.getenv does NOT see .env values in this codebase -
        # pydantic-settings populates Settings, not os.environ.
        if api_key:
            self._api_key = api_key
        else:
            self._api_key = ""
            try:
                from app.config import get_settings
                self._api_key = (get_settings().mem0_api_key or "").strip()
            except Exception:  # noqa: BLE001
                pass
            if not self._api_key:
                self._api_key = os.getenv("MEM0_API_KEY", "").strip()
        self._client = None
        self._available = False
        self._init_client()

    def _init_client(self) -> None:
        if not self._api_key:
            logger.warning(
                "Mem0 disabled: MEM0_API_KEY missing. "
                "Agents will operate without shared memory."
            )
            return
        try:
            # Lazy import so agents that don't use memory don't pay
            # the import cost.
            from mem0 import MemoryClient

            self._client = MemoryClient(api_key=self._api_key)
            self._available = True
            logger.info("Mem0 client ready (user_id=%s)", self.user_id)
        except ImportError:
            logger.warning(
                "Mem0 SDK not installed. Run: "
                "pip install mem0ai - then restart agents."
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("Mem0 init failed: %s. Operating without memory.", e)

    # ------------------------------------------------------------------
    # Decision logging
    # ------------------------------------------------------------------

    def log_decision(self, decision: AgentDecision) -> Optional[str]:
        """
        Persist an agent decision to Mem0. Returns the memory ID on
        success, None on failure. Never raises.
        """
        if not self._available or _writes_paused():
            return None
        if not _budget_try_spend("add"):
            _budget_throttle_log("add")
            return None
        try:
            content = self._format_decision(decision)
            metadata = {
                "kind": "decision",
                "agent": decision.agent,
                "action": decision.action,
                "ticker": decision.ticker,
                "timestamp": decision.timestamp,
                **decision.metadata,
            }
            result = self._client.add(
                messages=[{"role": "assistant", "content": content}],
                user_id=self.user_id,
                metadata=normalize_tags(metadata),
            )
            # Mem0 v3 processes adds ASYNCHRONOUSLY: the response is
            # {"event_id": ..., "status": "PENDING"} with no memory id.
            # Callers correlate decisions->outcomes via the client-side
            # decision_key in metadata instead (Task #47, 2026-06-12).
            rid = self._extract_id(result)
            if rid is None and isinstance(result, dict) and result.get("event_id"):
                rid = str(metadata.get("decision_key") or result["event_id"])
            return rid
        except Exception as e:  # noqa: BLE001
            _maybe_pause_writes(e)
            logger.warning(
                "Mem0 log_decision failed for %s/%s: %s",
                decision.agent, decision.ticker, e,
            )
            return None

    def log_outcome(self, outcome: TradeOutcome) -> Optional[str]:
        """
        Persist a closed-trade outcome. Reference the decisions that
        led to it via outcome.related_decisions so the loop closes.
        """
        if not self._available or _writes_paused():
            return None
        if not _budget_try_spend("add"):
            _budget_throttle_log("add")
            return None
        try:
            content = self._format_outcome(outcome)
            metadata = {
                "kind": "outcome",
                "ticker": outcome.ticker,
                "side": outcome.side,
                "exit_reason": outcome.exit_reason,
                "strategy": outcome.strategy,
                "pnl_usd": outcome.realized_pnl_usd,
                "holding_days": outcome.holding_days,
                "won": outcome.realized_pnl_usd > 0,
                "timestamp": outcome.timestamp,
                "related_decisions": outcome.related_decisions,
                **outcome.metadata,
            }
            result = self._client.add(
                messages=[{"role": "assistant", "content": content}],
                user_id=self.user_id,
                metadata=normalize_tags(metadata),
            )
            rid = self._extract_id(result)
            if rid is None and isinstance(result, dict) and result.get("event_id"):
                rid = str(result["event_id"])
            return rid
        except Exception as e:  # noqa: BLE001
            _maybe_pause_writes(e)
            logger.warning(
                "Mem0 log_outcome failed for %s: %s", outcome.ticker, e,
            )
            return None

    # ------------------------------------------------------------------
    # Recall - the value side of the loop
    # ------------------------------------------------------------------

    def recall_similar(
        self,
        query: str,
        limit: int = DEFAULT_RECALL_LIMIT,
        agent: Optional[str] = None,
        ticker: Optional[str] = None,
        kind: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """
        Semantic search for past memories similar to the query.

        query  - natural-language description of the current situation,
                 e.g. "AAPL setup with rsi 78 and broken trendline"
        agent  - optional filter on which agent created the memory
        ticker - optional filter on symbol
        kind   - 'decision' or 'outcome' or None for both
        """
        if not self._available:
            return []
        if not _budget_try_spend("search"):
            _budget_throttle_log("search")
            return []
        try:
            # Fixed 2026-06-11: mem0ai 2.x rejects top-level user_id in
            # search() ("Top-level entity parameters ... not supported.
            # Use filters={'user_id': ...}"). Every recall_similar call
            # had been failing silently since the 2.0.4 install -- agents
            # could WRITE memories but never READ them back. user_id now
            # rides in filters; agent/ticker/kind are filtered client-side
            # so we don't depend on Mem0's metadata-filter schema.
            results = self._client.search(
                query=query,
                filters={"user_id": self.user_id},
                limit=max(int(limit) * 3, int(limit)),
            )
            rows = (results.get("results", [])
                    if isinstance(results, dict) else list(results))

            def _meta(r: Any) -> dict:
                return (r.get("metadata") or {}) if isinstance(r, dict) else {}

            if agent:
                rows = [r for r in rows if _meta(r).get("agent") == agent]
            if ticker:
                rows = [r for r in rows
                        if str(_meta(r).get("ticker", "")).upper() == ticker.upper()]
            if kind:
                rows = [r for r in rows if _meta(r).get("kind") == kind]
            return rows[:int(limit)]
        except Exception as e:  # noqa: BLE001
            logger.warning("Mem0 recall_similar failed for %r: %s", query, e)
            return []

    # ------------------------------------------------------------------
    # Health + utility
    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        return self._available

    def health(self) -> dict[str, Any]:
        return {
            "available": self._available,
            "user_id": self.user_id,
            "api_key_set": bool(self._api_key),
            "writes_paused": _writes_paused(),
            "budget": budget_status(),
        }

    # ------------------------------------------------------------------
    # Internal formatting
    # ------------------------------------------------------------------

    @staticmethod
    def _format_decision(d: AgentDecision) -> str:
        meta_str = ", ".join(f"{k}={v}" for k, v in d.metadata.items())
        head = f"[{d.agent}] {d.action.upper()} {d.ticker}"
        body = d.reasoning
        if meta_str:
            body = f"{body} ({meta_str})"
        return f"{head}: {body}"

    @staticmethod
    def _format_outcome(o: TradeOutcome) -> str:
        return (
            f"[OUTCOME] {o.ticker} {o.side} via {o.strategy} closed "
            f"{o.exit_reason} after {o.holding_days}d for "
            f"${o.realized_pnl_usd:+.2f} (entry {o.entry_price} "
            f"-> exit {o.exit_price})"
        )

    @staticmethod
    def _extract_id(result: Any) -> Optional[str]:
        if isinstance(result, dict):
            return result.get("id") or result.get("memory_id")
        if isinstance(result, list) and result:
            first = result[0]
            if isinstance(first, dict):
                return first.get("id") or first.get("memory_id")
        return None


# ----------------------------------------------------------------------
# Singleton accessor
# ----------------------------------------------------------------------

_memory_singleton: Optional[TrezoMemory] = None


def get_memory() -> TrezoMemory:
    """
    Return the process-wide TrezoMemory. Agents should call this once
    per module rather than constructing TrezoMemory directly.
    """
    global _memory_singleton
    if _memory_singleton is None:
        _memory_singleton = TrezoMemory()
    return _memory_singleton
