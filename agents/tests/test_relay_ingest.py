"""A briefing that doesn't fit must be refused out loud, and one that
fits must land where agents look -- and nowhere else.

relay_ingest (2026-08-21) is the receiving end of Nova's skills. Its two
promises are the two halves of this file:

  1. CONTEXT ONLY. It writes memory and `info` messages. It never emits
     an `event` (Adaptive Scope acts on those), never queues an ops job,
     never touches scope/posture/sizing. A refactor that adds any of
     that should fail here first.
  2. LOUD REJECTION. A malformed, unknown, stale or future-dated brief is
     marked `rejected` with the reason and announced. Silent skipping is
     the failure mode that lets a stale regime sit in memory for days.
"""
from __future__ import annotations

import asyncio
import inspect
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _bootstrap import load_module, run_tests, stub_config  # noqa: E402

stub_config()
base = load_module("app.agents.base")
ri = load_module("app.agents.relay_ingest")

NOW = datetime(2026, 8, 21, 19, 30, tzinfo=timezone.utc)


def _market(**over):
    p = {"as_of": NOW.isoformat(), "slot": "pre-close", "regime": "mixed",
         "indices": {"SPY": -0.3, "QQQ": -0.6}, "summary": "Chop into the close."}
    p.update(over)
    return p


def _wrap(**over):
    p = {"as_of": NOW.isoformat(), "trade_date": "2026-08-21", "realized_pnl_usd": 41.2,
         "target_pnl_usd": 1000.0, "open_positions": 9,
         "lanes": {"crypto": {"wins": 3, "losses": 2, "pnl": 20.1}},
         "summary": "Below target; crypto carried the day."}
    p.update(over)
    return p


def _health(**over):
    p = {"as_of": NOW.isoformat(), "verdict": "healthy",
         "findings": ["heartbeat 2m", "no alerts"], "summary": "Engine alive."}
    p.update(over)
    return p


# ---- validation -------------------------------------------------------

def test_valid_briefs_pass_for_every_kind():
    ri.validate("market_context", _market(), now=NOW)
    ri.validate("daily_wrap", _wrap(), now=NOW)
    ri.validate("health", _health(), now=NOW)


def test_unknown_kind_is_refused_with_the_allowed_list():
    try:
        ri.validate("posture_update", _market(), now=NOW)
    except ri.BriefingRejected as e:
        assert "unknown kind" in str(e) and "market_context" in str(e)
    else:
        raise AssertionError("an unknown kind was accepted")


def test_missing_field_names_the_field():
    p = _market(); del p["regime"]
    try:
        ri.validate("market_context", p, now=NOW)
    except ri.BriefingRejected as e:
        assert "regime" in str(e)
    else:
        raise AssertionError("a brief with no regime was accepted")


def test_bad_choice_is_refused():
    try:
        ri.validate("market_context", _market(regime="to the moon"), now=NOW)
    except ri.BriefingRejected as e:
        assert "regime" in str(e)
    else:
        raise AssertionError("an invented regime was accepted")


def test_bool_is_not_an_integer_position_count():
    try:
        ri.validate("daily_wrap", _wrap(open_positions=True), now=NOW)
    except ri.BriefingRejected:
        pass
    else:
        raise AssertionError("open_positions=True passed as an int")


def test_stale_brief_is_refused_not_filed():
    old = (NOW - timedelta(hours=60)).isoformat()
    try:
        ri.validate("market_context", _market(as_of=old), now=NOW)
    except ri.BriefingRejected as e:
        assert "stale" in str(e)
    else:
        raise AssertionError("a 60h-old tape read was accepted as current")


def test_future_dated_brief_is_refused():
    fut = (NOW + timedelta(hours=5)).isoformat()
    try:
        ri.validate("health", _health(as_of=fut), now=NOW)
    except ri.BriefingRejected as e:
        assert "future" in str(e)
    else:
        raise AssertionError("a future-dated brief was accepted")


def test_json_string_payload_is_accepted():
    import json
    out = ri.validate("health", json.dumps(_health()), now=NOW)
    assert out["verdict"] == "healthy"


# ---- separation + announcement (stubbed memory, no network) ----------

class _Harness:
    def __init__(self):
        self.memory = []
        self.marks = []

    def agent(self, fail_memory=False):
        a = ri.RelayIngestAgent()
        a._client_tried = True  # never build a real client

        async def remember(topic, content, *, scope="shared", category="insight", weight_delta=1.0):
            self.memory.append((scope, topic, category, content))
            return not fail_memory

        async def mark(rid, status, result):
            self.marks.append((rid, status, result))
        a.remember = remember
        a._mark = mark
        return a


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_each_kind_lands_in_its_own_scope_and_the_shared_pool():
    h = _Harness(); a = h.agent()
    rows = [
        {"id": "1", "kind": "market_context", "source": "market-report", "payload": _market()},
        {"id": "2", "kind": "daily_wrap", "source": "trezo-daily-wrap", "payload": _wrap()},
        {"id": "3", "kind": "health", "source": "trezo-server-sentinel", "payload": _health()},
    ]
    # validate() inside ingest() uses the real clock; pin as_of to now.
    for r in rows:
        r["payload"]["as_of"] = datetime.now(timezone.utc).isoformat()
    msgs = [_run(a.ingest(r)) for r in rows]

    scopes = {s for s, *_ in h.memory}
    assert scopes == {"relay:market", "relay:analytics", "relay:health", "shared"}, scopes
    shared_topics = {t for s, t, *_ in h.memory if s == "shared"}
    assert shared_topics == {"relay.market_context.latest", "relay.daily_wrap.latest",
                             "relay.health.latest"}, shared_topics
    assert [m.kind for m in msgs] == ["info", "info", "info"]
    assert all(st == "ingested" for _, st, _ in h.marks), h.marks


def test_rejection_is_marked_logged_and_announced():
    h = _Harness(); a = h.agent()
    row = {"id": "9", "kind": "market_context", "source": "market-report",
           "payload": _market(regime="bananas", as_of=datetime.now(timezone.utc).isoformat())}
    msg = _run(a.ingest(row))
    assert h.marks and h.marks[0][1] == "rejected" and "regime" in h.marks[0][2]
    assert msg.kind == "info" and msg.payload.get("severity") == "warning"
    assert not h.memory, "a rejected brief still reached memory"


def test_memory_failure_is_visible_in_the_row_and_the_message():
    h = _Harness(); a = h.agent(fail_memory=True)
    row = {"id": "5", "kind": "health", "source": "trezo-midday-snapshot",
           "payload": _health(as_of=datetime.now(timezone.utc).isoformat())}
    msg = _run(a.ingest(row))
    assert "FAILED" in h.marks[0][2]
    assert msg.payload.get("memory_ok") is False
    assert msg.payload.get("severity") == "warning"


# ---- context only: no path to act --------------------------------------

def test_the_agent_never_emits_event_messages():
    src = inspect.getsource(ri)
    assert not re.search(r"kind\s*=\s*[\"']event[\"']", src), (
        "relay_ingest emits `event` messages -- Adaptive Scope acts on those. "
        "That is soft-signal mode, a separate decision.")


def test_the_agent_has_no_on_message_and_no_ops_hook():
    assert "on_message" not in vars(ri.RelayIngestAgent), "relay_ingest reacts to bus traffic"
    src = inspect.getsource(ri)
    for forbidden in ("ops_tasks", "drain_once", "place_order", "submit_order",
                      "set_posture", "adaptive_scope", "regime_posture"):
        assert forbidden not in src, f"relay_ingest references {forbidden}"


def test_bad_rows_do_not_stop_the_batch():
    h = _Harness(); a = h.agent()
    good = {"id": "a", "kind": "health", "source": "s",
            "payload": _health(as_of=datetime.now(timezone.utc).isoformat())}
    poison = {"id": "b", "kind": "health", "source": "s", "payload": object()}

    async def fetch():
        return [poison, good]
    a._fetch_new = fetch
    msgs = _run(a.tick())
    kinds = [m.kind for m in msgs]
    assert "info" in kinds, f"the good row was lost behind the poison one: {kinds}"
    assert any(st == "rejected" for _, st, _ in h.marks)
    assert any(st == "ingested" for _, st, _ in h.marks)


if __name__ == "__main__":
    sys.exit(run_tests(dict(globals())))
