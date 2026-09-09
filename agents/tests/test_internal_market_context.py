"""Internal benchmark context reaches existing consumers with source expiry."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import load_module, run_tests, stub_config

stub_config()
context = load_module("app.knowledge.internal_market_context")
md = load_module("app.agents.market_desk")
data = load_module("app.brokers.alpaca_data")
activity = load_module("app.agents.activity_log")
NOW = datetime(2026, 9, 9, 15, 0, tzinfo=timezone.utc)


def _bar(price, stamp, **changes):
    result = {"o": price, "h": price * 1.05, "l": price * 0.95,
              "c": price, "v": 1000, "vw": price, "t": stamp}
    result.update(changes)
    return result


def _snapshots(*, now=NOW, direction="below"):
    factor = {"below": 0.99, "above": 1.01, "equal": 1.0}[direction]
    minute_at = (now - timedelta(minutes=2)).isoformat()
    local = now.astimezone(context._new_york_timezone())
    daily = local.replace(hour=0, minute=0, second=0, microsecond=0)
    previous = daily - timedelta(days=1)
    return {s: {"minuteBar": _bar(p * factor, minute_at),
                "dailyBar": _bar(p, daily.isoformat()),
                "prevDailyBar": _bar(p, previous.isoformat()),
                # Extra provider fields are not context or request instructions.
                "latestTrade": {"p": p * 100, "t": now.isoformat()},
                "untrusted_unused": "do not interpret"}
            for s, p in (("SPY", 100), ("QQQ", 200))}


@contextmanager
def _environment(raw=None, *, briefing=None, now=NOW):
    clock = SimpleNamespace(value=now)
    calls, records = [], []
    raw = _snapshots(now=now) if raw is None else raw

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock.value.astimezone(tz) if tz else clock.value.replace(tzinfo=None)

    async def get(path, params):
        calls.append((path, params))
        if isinstance(raw, BaseException):
            raise raw
        return deepcopy(raw)

    async def relay(self):
        return briefing

    with patch.object(md, "_current", None), patch.object(md, "_current_at", 0.0), \
            patch.object(md, "datetime", Clock), \
            patch.object(md.MarketDeskAgent, "_newest_briefing", relay), \
            patch.object(data, "_data_get", get), patch.object(data, "DATA_FEED", "iex"), \
            patch.object(activity, "record", lambda *args, **kw: records.append((args, kw))):
        yield SimpleNamespace(agent=md.MarketDeskAgent(), clock=clock, calls=calls,
                              records=records, raw=raw)


def test_tick_batches_both_symbols_and_serves_source_stamped_qualified_proxy():
    with _environment() as env:
        messages = asyncio.run(env.agent.tick())
        assert env.calls == [("/v2/stocks/snapshots", {"symbols": "SPY,QQQ", "feed": "iex"})]
        view = md.current_market_view()
        assert view is not None and view.regime == "risk_off"
        assert view.as_of == (NOW - timedelta(minutes=2)).isoformat()
        assert view.context_kind == "internal_benchmark_proxy" and view.max_age_seconds == 300
        assert view.vix is None and view.breadth == "" and view.movers_down == []
        assert view.catalysts == [] and view.movers_up == []
        assert view.provenance["feed_scope"] == "single_exchange_iex"
        assert view.provenance["missing_fields"] == list(context.MISSING_FIELDS)
        assert view.provenance["benchmarks"]["SPY"]["price_basis"] == "completed_minute_close"
        assert abs(view.indices["SPY"] + 1) < 1e-8
        assert "account" not in view.provenance and "latestTrade" not in json.dumps(view.provenance)
        assert messages[0].payload["event"] == "market_view" and len(env.records) == 1


def test_fresh_relay_takes_precedence_and_changed_same_timestamp_is_observed():
    briefing = {"source": "market-report", "payload": {
        "as_of": (NOW - timedelta(hours=1)).isoformat(), "regime": "mixed", "slot": "morning"}}
    with _environment(briefing=briefing) as env:
        assert len(asyncio.run(env.agent.tick())) == 1
        assert md.current_market_view().context_kind == "relay_report"
        assert md.current_market_view().max_age_seconds == 86400
        assert env.calls == []
        assert asyncio.run(env.agent.tick()) == []
        briefing["payload"]["regime"] = "risk_off"
        assert len(asyncio.run(env.agent.tick())) == 1
        assert md.current_market_view().regime == "risk_off" and env.calls == []


def test_stale_or_malformed_relay_allows_fallback():
    rows = [{"source": "old", "payload": {"as_of": (NOW - timedelta(days=2)).isoformat()}},
            {"payload": {"as_of": NOW.isoformat(), "indices": [1, 2]}},
            {"payload": "malformed"}]
    for row in rows:
        with _environment(briefing=row) as env:
            asyncio.run(env.agent.tick())
            assert len(env.calls) == 1
            assert md.current_market_view().context_kind == "internal_benchmark_proxy"


def test_same_snapshot_dedupes_receipts_restores_pointer_and_cannot_extend_ttl():
    with _environment() as env:
        asyncio.run(env.agent.tick())
        source = md.current_market_view().as_of
        md._current = None
        env.clock.value += timedelta(minutes=1)
        assert asyncio.run(env.agent.tick()) == []
        assert md.current_market_view().as_of == source and len(env.records) == 1
        env.clock.value = NOW + timedelta(minutes=3, seconds=1)
        assert md.current_market_view() is None
        result = asyncio.run(env.agent.tick())[0].payload
        assert result["status"] == "invalid" and result["reason"] == "stale_minute_bar"
        assert md.current_market_view() is None and len(env.records) == 1
        env.raw.clear()
        env.raw.update(_snapshots(now=env.clock.value))
        result = asyncio.run(env.agent.tick())
        assert result[0].payload["event"] == "market_view"
        assert md.current_market_view().as_of != source


def test_failed_relay_read_retains_valid_relay_until_its_own_source_expiry():
    with _environment() as env:
        md._current = md.build_view({"as_of": (NOW - timedelta(hours=1)).isoformat(),
                                     "regime": "mixed"}, source="retained-report")
        assert asyncio.run(env.agent.tick()) == [] and env.calls == []
        md._current.as_of = (NOW - timedelta(hours=25)).isoformat()
        asyncio.run(env.agent.tick())
        assert len(env.calls) == 1 and md.current_market_view().context_kind == "internal_benchmark_proxy"


def test_partial_benchmark_or_invalid_bars_never_publish_direction():
    changes = [("minuteBar", "c", None), ("minuteBar", "c", float("nan")),
               ("minuteBar", "c", True), ("minuteBar", "v", 0),
               ("dailyBar", "v", -1), ("dailyBar", "vw", float("inf")),
               ("dailyBar", "vw", 99999), ("prevDailyBar", "c", 0),
               ("minuteBar", "t", "2026-09-09T14:58:00"),
               ("minuteBar", "t", "nonsense")]
    for bar, key, value in changes:
        raw = _snapshots()
        raw["QQQ"][bar][key] = value
        with _environment(raw) as env:
            receipt = asyncio.run(env.agent.tick())[0].payload
            assert receipt["status"] == "invalid" and receipt["symbol"] == "QQQ"
            assert receipt["as_of"] is None and md.current_market_view() is None
            assert env.records == []
    raw = _snapshots()
    del raw["QQQ"]
    result = context.build_context(raw, feed="iex", now=NOW)
    assert result.reason == "missing_benchmark_snapshot" and result.payload is None


def test_unfinished_future_stale_and_cross_session_sources_are_rejected():
    cases = [("minuteBar", NOW + timedelta(seconds=1), "future_bar"),
             ("minuteBar", NOW - timedelta(seconds=30), "unfinished_minute_bar"),
             ("minuteBar", NOW - timedelta(minutes=6), "stale_minute_bar"),
             ("dailyBar", NOW - timedelta(days=1), "cross_session_bar"),
             ("dailyBar", NOW + timedelta(days=1), "future_bar"),
             ("prevDailyBar", NOW, "invalid_previous_session"),
             ("prevDailyBar", NOW - timedelta(days=11), "invalid_previous_session")]
    for bar, stamp, expected in cases:
        raw = _snapshots()
        raw["QQQ"][bar]["t"] = stamp.isoformat()
        result = context.build_context(raw, feed="iex", now=NOW)
        assert result.reason == expected and result.payload is None, result


def test_both_benchmarks_set_proxy_direction_with_equal_or_disagreeing_as_mixed():
    for direction, regime in (("below", "risk_off"), ("above", "risk_on"), ("equal", "mixed")):
        result = context.build_context(_snapshots(direction=direction), feed="iex", now=NOW)
        assert result.status == "ready" and result.payload["regime"] == regime
    raw = _snapshots()
    raw["QQQ"] = _snapshots(direction="above")["QQQ"]
    assert context.build_context(raw, feed="iex", now=NOW).payload["regime"] == "mixed"


def test_oldest_source_sets_expiry_and_polling_time_does_not_change_identity():
    raw = _snapshots()
    raw["SPY"]["minuteBar"]["t"] = (NOW - timedelta(minutes=4)).isoformat()
    first = context.build_context(raw, feed="iex", now=NOW)
    again = context.build_context(raw, feed="iex", now=NOW + timedelta(seconds=30))
    assert first.payload == again.payload
    assert first.payload["as_of"] == raw["SPY"]["minuteBar"]["t"]
    changed = deepcopy(raw)
    changed["SPY"]["dailyBar"]["vw"] -= 0.1
    revised = context.build_context(changed, feed="iex", now=NOW)
    assert revised.payload["provenance"]["snapshot_id"] != first.payload["provenance"]["snapshot_id"]


def test_no_request_outside_session_and_no_false_success_on_adapter_errors():
    with _environment(now=NOW.replace(hour=2)) as env:
        receipt = asyncio.run(env.agent.tick())[0].payload
        assert receipt["reason"] == "outside_regular_equity_context_window" and env.calls == []
    with _environment(RuntimeError("secret provider error")) as env:
        receipt = asyncio.run(env.agent.tick())[0].payload
        assert receipt["status"] == "unavailable" and receipt["error_type"] == "RuntimeError"
        assert "secret" not in json.dumps(receipt) and md.current_market_view() is None
    async def missing(*args, **kwargs):
        return None
    with patch.object(data, "_data_get", missing):
        result = asyncio.run(context.fetch_context(now=NOW))
        assert result.reason == "snapshot_data_unavailable" and result.payload is None


def test_timezone_and_source_age_bounds_remain_valid_across_winter_dst():
    winter = datetime(2026, 12, 9, 15, tzinfo=timezone.utc)
    result = context.build_context(_snapshots(now=winter), feed="iex", now=winter)
    assert result.status == "ready"
    assert result.payload["provenance"]["benchmarks"]["SPY"]["session_bar"]["t"].startswith("2026-12-09T05:00")
    assert context.build_context(_snapshots(), feed="iex", now=NOW.replace(tzinfo=None)).payload is None
    for maximum in (0, -1, True, float("nan"), float("inf"), 86401, "300"):
        view = md.build_view({"as_of": NOW.isoformat()}, max_age_seconds=maximum)
        assert not view.fresh(now=NOW)


def test_extreme_finite_prices_cannot_emit_infinite_percentages():
    raw = _snapshots()
    raw["SPY"]["prevDailyBar"].update(o=1e-308, h=1e-308, l=1e-308, c=1e-308)
    raw["SPY"]["minuteBar"].update(o=1e308, h=1e308, l=1e308, c=1e308)
    result = context.build_context(raw, feed="iex", now=NOW)
    assert result.reason == "nonfinite_index_change" and result.payload is None
    json.dumps(result.receipt(), allow_nan=False)


def test_missing_system_timezone_uses_existing_pytz_with_correct_dst():
    with patch.object(context, "ZoneInfo", side_effect=context.ZoneInfoNotFoundError("no system database")):
        for now, utc_midnight in ((NOW, "04:00"),
                                  (datetime(2026, 12, 9, 15, tzinfo=timezone.utc), "05:00")):
            result = context.build_context(_snapshots(now=now), feed="iex", now=now)
            assert result.status == "ready", result
            stamp = result.payload["provenance"]["benchmarks"]["SPY"]["session_bar"]["t"]
            assert stamp[11:16] == utc_midnight
    with patch.object(context, "_new_york_timezone", side_effect=context.TimezoneUnavailable("missing")):
        result = asyncio.run(context.fetch_context(now=NOW))
        assert result.status == "unavailable" and result.reason == "new_york_timezone_unavailable"


def test_real_risk_consumer_tightens_equity_only_and_stale_context_restores_baseline():
    # Reuse the existing executed-handler harness; every external seam and
    # activity writer is patched there, and this scope restores the Desk pointer.
    from tests import test_risk_manager_bookkeyed as risk
    with _environment() as env, risk._desk(states=risk.TWO_OPEN,
                                          books=risk._two_floors(), pass_market=True) as (agent, calls):
        baseline = risk._verdict(asyncio.run(agent.on_message(risk._stock(tcs=42))))
        assert baseline.kind == "approve", baseline.payload
        asyncio.run(env.agent.tick())
        tightened = risk._verdict(asyncio.run(agent.on_message(risk._stock(tcs=42))))
        assert tightened.kind == "veto" and "below threshold 45" in tightened.payload["reason"]
        assert "market report" in tightened.payload["reason"]
        crypto = risk._verdict(asyncio.run(agent.on_message(risk._signal(tcs=40))))
        assert crypto.kind == "approve", crypto.payload
        env.clock.value += timedelta(minutes=4)
        assert md.current_market_view() is None
        restored = risk._verdict(asyncio.run(agent.on_message(risk._stock(tcs=42))))
        assert restored.kind == "approve", restored.payload
        assert calls.alpaca_get_account == 0


def test_upward_proxy_does_not_loosen_risk_or_invent_wheel_pressure():
    from tests import test_risk_manager_bookkeyed as risk
    advisor = load_module("app.strategies.wheel_advisor")
    with _environment(_snapshots(direction="above")) as env, \
            risk._desk(states=risk.TWO_OPEN, books=risk._two_floors(), pass_market=True) as (agent, _):
        asyncio.run(env.agent.tick())
        view = md.current_market_view()
        assert view.regime == "risk_on"
        verdict = risk._verdict(asyncio.run(agent.on_message(risk._stock(tcs=39))))
        assert verdict.kind == "veto" and "below threshold 40" in verdict.payload["reason"]
        assert advisor.check_market_pressure("wheel_csp", "SPY", movers_down=view.movers_down).allow


if __name__ == "__main__":
    raise SystemExit(run_tests(globals()))
