"""Exercise the real discovery -> internal research -> durable artifacts path."""

from __future__ import annotations

import asyncio
from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import load_module, run_tests, stub_config

stub_config()
bridge = load_module("app.research.bridge")
discovery = load_module("app.agents.strategy_discovery")
performance = load_module("app.paper.performance")


@contextmanager
def _patched(target, **attrs):
    old = {key: getattr(target, key) for key in attrs}
    try:
        for key, value in attrs.items():
            setattr(target, key, value)
        yield
    finally:
        for key, value in old.items():
            setattr(target, key, value)


def _settings(path, **overrides):
    values = dict(trezo_research_enabled=True, trading_mode="paper",
                  trezo_research_symbol="SPY", trezo_research_asset_type="stock",
                  trezo_research_capital_mode="fixed_scenario",
                  trezo_research_capitals="1000,5000",
                  trezo_research_commission_bps=2, trezo_research_slippage_bps=5,
                  trezo_research_db_path=str(path))
    values.update(overrides)
    return SimpleNamespace(**values)


def _candles():
    # Synthetic evidence for plumbing tests, never a market-return claim.
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0,
                                              microsecond=0) - timedelta(days=502)
    rows = []
    for i in range(500):
        price = 100 + 0.03 * i + 4 * math.sin(i / 9)
        rows.append(SimpleNamespace(timestamp=start + timedelta(days=i),
                                    open=price, high=price + 1, low=price - 1,
                                    close=price + 0.2, volume=100000))
    return rows


async def _forbidden_fetch(*args):
    raise AssertionError("research must not fetch data in this state")


def test_disabled_or_missing_costs_do_not_fetch_or_create_files():
    with tempfile.TemporaryDirectory() as tmp, _patched(bridge, _fetch_daily=_forbidden_fetch):
        path = Path(tmp) / "research.sqlite3"
        result = asyncio.run(bridge.research_for_book("book-a", settings=_settings(
            path, trezo_research_enabled=False)))
        assert result["status"] == "disabled"
        result = asyncio.run(bridge.research_for_book("book-a", settings=_settings(
            path, trezo_research_commission_bps=None)))
        assert result["status"] == "blocked"
        assert not path.exists()


def test_invalid_identity_mode_and_configuration_cannot_start_research():
    with tempfile.TemporaryDirectory() as tmp, _patched(bridge, _fetch_daily=_forbidden_fetch):
        path = Path(tmp) / "research.sqlite3"
        for uid, changes in [("", {}), ("book-a", {"trading_mode": "live"}),
                             ("book-a", {"trezo_research_symbol": "../../bad"}),
                             ("book-a", {"trezo_research_capitals": "1000,5000,10000"}),
                             ("book-a", {"trezo_research_slippage_bps": float("nan")})]:
            result = asyncio.run(bridge.research_for_book(uid, settings=_settings(path, **changes)))
            assert result["status"] == "blocked", result
        assert not path.exists()


def test_stale_daily_data_cannot_complete_a_cycle():
    async def stale(*args):
        rows = _candles()
        for row in rows:
            row.timestamp -= timedelta(days=30)
        return rows

    with tempfile.TemporaryDirectory() as tmp, _patched(bridge, _fetch_daily=stale, _DATA_CACHE={}):
        path = Path(tmp) / "research.sqlite3"
        result = asyncio.run(bridge.research_for_book("book-a", settings=_settings(path)))
        assert result["status"] == "blocked", result
        assert result["reason"] == "insufficient_or_stale_completed_daily_bars"
        assert not path.exists()


def test_real_discovery_tick_creates_reuses_and_isolates_research_artifacts():
    fetches = []

    async def data(symbol, asset_type):
        fetches.append((symbol, asset_type))
        return _candles()

    class Client:
        def table(self, name):
            assert name == "paper_accounts"
            return self

        def select(self, fields):
            assert fields == "user_id"
            return self

        def execute(self):
            return SimpleNamespace(data=[{"user_id": "book-a"}, {"user_id": "book-b"}])

    async def report(client, uid):
        return performance.compute_performance([])

    async def no_recall(*args, **kwargs):
        return []

    async def no_remember(*args, **kwargs):
        return True

    async def no_insight(*args, **kwargs):
        return ""

    with tempfile.TemporaryDirectory() as tmp, ExitStack() as patches:
        path = Path(tmp) / "research.sqlite3"
        cfg = _settings(path)
        patches.enter_context(_patched(bridge, _fetch_daily=data, _DATA_CACHE={},
                                       get_settings=lambda: cfg))
        patches.enter_context(_patched(discovery, _supabase=lambda: Client(),
                                       performance_for_user=report))
        patches.enter_context(_patched(discovery.StrategyDiscoveryAgent,
                                       recall=no_recall, remember=no_remember,
                                       _backtest_insight=no_insight))
        # New instances model a restarted agent; SQLite retains the cycle identity.
        messages = asyncio.run(discovery.StrategyDiscoveryAgent().tick())
        first_artifacts = {p: p.read_bytes() for p in Path(tmp).rglob("*.json")}
        repeated = asyncio.run(discovery.StrategyDiscoveryAgent().tick())
        assert first_artifacts == {p: p.read_bytes() for p in Path(tmp).rglob("*.json")}
        research = [m.payload for m in messages if m.payload.get("event") == "internal_research"]
        again = [m.payload for m in repeated if m.payload.get("event") == "internal_research"]
        assert len(research) == len(again) == 2, messages
        assert all(r["status"] == "completed" for r in research), research
        assert all(r["execution_enabled"] is False and r["llm_calls"] == 0 for r in research)
        assert [c["job_id"] for r in research for c in r["cases"]] == [
            c["job_id"] for r in again for c in r["cases"]]
        cases = [c for r in research for c in r["cases"]]
        assert len({c["job_id"] for c in cases}) == 4  # two books, two capitals
        assert all(c["trial_count"] == 4 for c in cases), cases
        assert len(list(Path(tmp).rglob("*.json"))) == 4
        for case in cases:
            artifact = json.loads(Path(case["artifact_path"]).read_text())
            assert artifact["job_id"] == case["job_id"]
            assert artifact["execution_enabled"] is False
            assert artifact["forward_evidence_required"] is True
        assert fetches == [("SPY", "stock")], fetches


def test_failed_market_data_is_visible_and_retryable():
    calls = []

    async def data(*args):
        calls.append(1)
        raise RuntimeError("synthetic provider failure")

    with tempfile.TemporaryDirectory() as tmp, _patched(bridge, _fetch_daily=data, _DATA_CACHE={}):
        path = Path(tmp) / "research.sqlite3"
        cfg = _settings(path)
        for uid in ("book-a", "book-b"):
            result = asyncio.run(bridge.research_for_book(uid, settings=cfg))
            assert result["status"] == "failed"
            assert result["reason"] == "market_data_unavailable"
        assert len(calls) == 2 and not path.exists()


if __name__ == "__main__":
    raise SystemExit(run_tests(globals()))
