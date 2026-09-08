"""Backtest history must influence only the book that owns the run.

Exercise the real scanner tick and selector with fake data boundaries. No
engine startup, broker calls, database writes, pytest fixtures or .env.
"""

from __future__ import annotations

import asyncio
from contextlib import ExitStack, contextmanager
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import load_module, run_tests, stub_config

stub_config()
scanner = load_module("app.agents.pattern_detection")
selector = load_module("app.strategies.selector")
settings = load_module("app.runtime.settings")
edges = load_module("app.learning.strategy_weighting")
cycles = load_module("app.data.cycles")
overrides = load_module("app.runtime.overrides")


@contextmanager
def _patched(target, **attrs):
    missing = object()
    previous = {key: getattr(target, key, missing) for key in attrs}
    try:
        for key, value in attrs.items():
            setattr(target, key, value)
        yield
    finally:
        for key, value in previous.items():
            if value is missing:
                delattr(target, key)
            else:
                setattr(target, key, value)


class _Client:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []
        self.failed = set()

    def table(self, name):
        assert name == "backtest_runs"
        return _Query(self)


class _Query:
    def __init__(self, client):
        self.client = client
        self.uid = None

    def select(self, fields):
        assert fields == "symbol, strategy, total_return_pct, trades"
        return self

    def eq(self, field, value):
        assert field == "user_id" and value
        self.uid = value
        return self

    def order(self, field, desc=False):
        assert field == "created_at" and desc is True
        return self

    def limit(self, limit):
        assert limit == 600
        return self

    def execute(self):
        # A missing tenant predicate fails even if all sample rows would
        # happen to pick the same strategy.
        assert self.uid is not None, "service-role query must bind a book"
        self.client.calls.append(self.uid)
        if self.uid in self.client.failed:
            raise RuntimeError("history temporarily unavailable")
        return SimpleNamespace(data=self.client.rows.get(self.uid, []))


def _rows(default, pattern):
    return [
        {"symbol": "AMD", "strategy": "default", "trades": 12,
         "total_return_pct": default},
        {"symbol": "AMD", "strategy": "pattern", "trades": 12,
         "total_return_pct": pattern},
    ]


def _client():
    return _Client({"book-a": _rows(8, -5), "book-b": _rows(-9, 4)})


def test_real_tick_selects_from_each_books_own_backtests():
    client = _client()
    agent = scanner.PatternDetectionAgent()
    agent._seeded_prev_strategy = True

    async def targets():
        return [("book-a", ["AMD"]), ("book-b", ["AMD"]), (None, ["AMD"])]

    async def pool(tickers, limit):
        return list(tickers), {"watchlist": len(tickers), "market_wide": 0}

    async def candles(*args):
        return [object()]

    async def no_edge(uid):
        return {}

    async def no_override(uid, symbol):
        return None

    async def cycle(symbol):
        return SimpleNamespace(iv_environment="normal", days_until_earnings=None,
                               days_until_exdiv=None, earnings_time=None)

    def score(*args, **kwargs):
        return SimpleNamespace(tcs=80, score=80, direction="bullish",
                               dominant_pattern="test", detected_patterns=[],
                               breakdown={})

    with ExitStack() as patches:
        patches.enter_context(_patched(agent, _scan_targets=targets))
        patches.enter_context(_patched(scanner, _supabase=lambda: client,
            fetch_candles_for=candles, expanded_scan_pool=pool,
            confluence_bonus=lambda _: {"bonus": 0},
            eligible_strategies=lambda *args, **kwargs: ["default", "pattern"],
            _stms_window=lambda: False, _orb_window=lambda: (False, ""),
            _swing_window=lambda: False))
        patches.enter_context(_patched(settings,
            get_bot_settings=lambda uid: settings.BotSettings()))
        patches.enter_context(_patched(selector, calculate_score=score))
        patches.enter_context(_patched(edges, get_live_strategy_edge=no_edge))
        patches.enter_context(_patched(cycles, get_cycle_position=cycle))
        patches.enter_context(_patched(overrides, get_strategy_override=no_override))
        messages = asyncio.run(agent.tick())

    assert not [msg for msg in messages if msg.kind == "error"], messages
    signals = {msg.payload.get("user_id"): msg.payload
               for msg in messages if msg.kind == "signal"}
    assert set(signals) == {"book-a", "book-b", None}, signals
    assert signals["book-a"]["strategy"] == "default"
    assert signals["book-b"]["strategy"] == "pattern"
    assert all(row["backtest_return_pct"] is None
               for row in signals[None]["strategy_selection"]["considered"])
    assert client.calls == ["book-a", "book-b"], client.calls


def test_failed_refresh_keeps_only_own_cache_and_retries():
    client = _client()
    agent = scanner.PatternDetectionAgent()
    clock = SimpleNamespace(time=lambda: 1000.0)
    with _patched(scanner, _supabase=lambda: client, time=clock):
        first_a = asyncio.run(agent._backtest_history("book-a"))
        first_b = asyncio.run(agent._backtest_history("book-b"))
        clock.time = lambda: 2000.0
        client.failed.add("book-a")
        assert asyncio.run(agent._backtest_history("book-a")) == first_a
        assert asyncio.run(agent._backtest_history("book-b")) == first_b
        assert agent._bt_at["book-a"] == 1000.0
        assert agent._bt_at["book-b"] == 2000.0
        client.failed.clear()
        client.rows["book-a"] = _rows(11, -2)
        fresh = asyncio.run(agent._backtest_history("book-a"))
    assert fresh["AMD"]["default"] == 11
    assert client.calls.count("book-a") == 3
    assert first_b["AMD"]["default"] == -9


def test_failed_cold_book_cannot_inherit_a_warm_books_cache():
    client = _client()
    agent = scanner.PatternDetectionAgent()
    with _patched(scanner, _supabase=lambda: client):
        assert asyncio.run(agent._backtest_history("book-a"))
        client.failed.add("book-b")
        assert asyncio.run(agent._backtest_history("book-b")) == {}
        assert "book-b" not in agent._bt_at
        client.failed.clear()
        assert asyncio.run(agent._backtest_history("book-b"))["AMD"]["pattern"] == 4


def test_successful_empty_history_is_cached_only_for_its_book():
    client = _client()
    client.rows["book-b"] = []
    agent = scanner.PatternDetectionAgent()
    with _patched(scanner, _supabase=lambda: client):
        assert asyncio.run(agent._backtest_history("book-a"))
        assert asyncio.run(agent._backtest_history("book-b")) == {}
        assert asyncio.run(agent._backtest_history("book-b")) == {}
    assert client.calls == ["book-a", "book-b"]


def test_unscoped_fallback_never_reads_private_history():
    agent = scanner.PatternDetectionAgent()

    def forbidden():
        raise AssertionError("unscoped history must not query Supabase")

    with _patched(scanner, _supabase=forbidden):
        assert asyncio.run(agent._backtest_history(None)) == {}
        assert asyncio.run(agent._backtest_history("")) == {}


def test_disconnected_client_cannot_mix_cached_books():
    client = _client()
    agent = scanner.PatternDetectionAgent()
    clock = SimpleNamespace(time=lambda: 1000.0)
    with _patched(scanner, _supabase=lambda: client, time=clock):
        first = asyncio.run(agent._backtest_history("book-a"))
        clock.time = lambda: 2000.0
        with _patched(scanner, _supabase=lambda: None):
            assert asyncio.run(agent._backtest_history("book-a")) == first
            assert asyncio.run(agent._backtest_history("book-b")) == {}
            assert agent._bt_at == {"book-a": 1000.0}


if __name__ == "__main__":
    raise SystemExit(run_tests(globals()))
