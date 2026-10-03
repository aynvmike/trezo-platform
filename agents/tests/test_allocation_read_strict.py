"""Entry allocation never interprets an unavailable ledger as unused budget.

Plain guard functions: no fixtures, environment credentials or network.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager, ExitStack
from datetime import datetime, timezone
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import load_module, run_tests, stub_config

stub_config()
allocation = load_module("app.paper.allocation")
settings = load_module("app.runtime.settings")
execution = load_module("app.agents.trade_execution")
universe = load_module("app.data.market_universe")
alpaca = load_module("app.brokers.alpaca")
quotes = load_module("app.brokers.alpaca_data")
tokens = load_module("app.integrations.web_tokens")
sizing = load_module("app.paper.sizing")


class _Client:
    def __init__(self, by_book):
        self.by_book = by_book
        self.reads = []

    def table(self, name):
        assert name == "paper_positions"
        client = self

        class Query:
            def __init__(self):
                self.filters = {}

            def select(self, fields):
                return self

            def eq(self, key, value):
                self.filters[key] = value
                return self

            def execute(self):
                assert self.filters["status"] == "open"
                uid = self.filters["user_id"]
                client.reads.append(uid)
                result = client.by_book[uid]
                if isinstance(result, Exception):
                    raise result
                return SimpleNamespace(data=result)

        return Query()


def _row(quantity=2, price=100, asset_type="crypto", strategy="crypto_swing"):
    return {"quantity": quantity, "entry_price": price,
            "asset_type": asset_type, "strategy": strategy}


@contextmanager
def _world(client, budgets=None):
    budgets = budgets or {"book-a": 1000, "book-b": 2000}

    async def equity(uid):
        return 50000.0

    def book_settings(uid):
        return settings.BotSettings(allocation_overrides={"crypto": budgets[uid]})

    with ExitStack() as stack:
        stack.enter_context(patch.object(allocation, "_supabase", return_value=client))
        stack.enter_context(patch.object(allocation, "effective_equity", equity))
        stack.enter_context(patch.object(settings, "get_bot_settings", book_settings))
        stack.enter_context(patch.object(universe, "surge_day", return_value=False))
        stack.enter_context(patch.dict(os.environ, {
            "TREZO_HARD_POCKET_MIN_EQUITY": "0", "TREZO_INTRADAY_OVERFLOW_PCT": "0"}))
        yield


def _gate(uid):
    return asyncio.run(execution.TradeExecutionAgent()._allocation_gate(
        uid, 50000, "crypto_swing", "crypto"))


def test_failed_or_missing_exposure_is_unknown_and_only_verified_empty_is_zero():
    for client in (None, _Client({"book-a": RuntimeError("unavailable")}),
                   _Client({"book-a": None}), _Client({"book-a": {}})):
        with _world(client):
            assert asyncio.run(allocation.deployed_capital_strict("book-a")) is None
    with _world(_Client({"book-a": []})):
        result = asyncio.run(allocation.deployed_capital_strict("book-a"))
        assert result == {mt: 0.0 for mt in allocation.MARKET_TYPES}


def test_invalid_exposure_rows_cannot_invent_remaining_budget():
    for row in ({}, None, _row(quantity="bad"), _row(quantity=-1),
                _row(price=0), _row(price=float("nan")),
                _row(quantity=float("inf")), _row(quantity=1e308, price=1e308)):
        with _world(_Client({"book-a": [row]})):
            assert asyncio.run(allocation.deployed_capital_strict("book-a")) is None


def test_advisory_fallback_cannot_escape_the_real_entry_allocation_gate():
    client = _Client({"book-a": RuntimeError("database unavailable")})
    with _world(client):
        # Kept only for existing preview/proposal consumers.
        assert asyncio.run(allocation.deployed_capital("book-a"))["crypto"] == 0
        try:
            _gate("book-a")
        except ValueError as exc:
            assert "exposure unavailable" in str(exc)
        else:
            raise AssertionError("entry allocation accepted guessed zero exposure")


def test_each_book_uses_only_its_own_exposure_and_budget():
    client = _Client({"book-a": [_row(2, 100), _row(5, 10, "stock", "swing")],
                      "book-b": [_row(3, 100)]})
    with _world(client):
        assert _gate("book-a")[:4] == ("crypto", 1000, 200, 800)
        assert _gate("book-b")[:4] == ("crypto", 2000, 300, 1700)
    assert client.reads == ["book-a", "book-b"]


def test_one_book_read_failure_does_not_poison_a_healthy_sibling():
    client = _Client({"book-a": RuntimeError("book read failed"),
                      "book-b": [_row(3, 100)]})
    with _world(client):
        try:
            _gate("book-a")
        except ValueError:
            pass
        else:
            raise AssertionError("unreadable book was admitted")
        assert _gate("book-b")[:4] == ("crypto", 2000, 300, 1700)


def test_failed_allocation_read_stops_actual_crypto_entry_before_sizing_or_order():
    client = _Client({"book-a": RuntimeError("late database outage")})
    quote = SimpleNamespace(bid=100.0, ask=100.1,
                            ts=datetime.now(timezone.utc).isoformat())
    account = SimpleNamespace(trading_blocked=False, equity=50000)
    submitted = AsyncMock(side_effect=AssertionError("must not submit on unknown exposure"))
    with _world(client), \
         patch.object(tokens, "get_user_broker_token", AsyncMock(return_value=None)), \
         patch.object(alpaca, "get_account", AsyncMock(return_value=account)), \
         patch.object(quotes, "get_crypto_quote", AsyncMock(return_value=quote)), \
         patch.object(sizing, "plan_position", side_effect=AssertionError("must not size unknown exposure")), \
         patch.object(alpaca, "submit_crypto_order", submitted):
        try:
            asyncio.run(execution.TradeExecutionAgent()._execute_alpaca_crypto(
                "book-a", "BTC", "long", 1, .02, .02, "crypto_swing", {}))
        except ValueError as exc:
            assert "exposure unavailable" in str(exc)
        else:
            raise AssertionError("late failed ledger read did not stop actual entry")
    assert submitted.await_count == 0
    assert client.reads == ["book-a"]


if __name__ == "__main__":
    sys.exit(run_tests(dict(vars())))
