"""The direct income buy path requires verified book settings and exposure."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager, ExitStack
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import load_module, run_tests, stub_config

stub_config()
accumulator = load_module("app.dividends.accumulator")
allocation = load_module("app.paper.allocation")
settings = load_module("app.runtime.settings")
accounts = load_module("app.brokers.accounts")
routes = load_module("app.brokers.route_guard")
alpaca = load_module("app.brokers.alpaca")


class _Client:
    def __init__(self, tables):
        self.tables = tables
        self.reads = []

    def table(self, name):
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
                uid = self.filters["user_id"]
                client.reads.append((name, uid))
                if name == "paper_positions":
                    assert self.filters["status"] == "open"
                result = client.tables[name][uid]
                if isinstance(result, Exception):
                    raise result
                return SimpleNamespace(data=result)

        return Query()


def _cfg(**kwargs):
    values = {"allocation_overrides": {"income": 10000},
              "auto_trade_enabled": True, "dividend_lt_enabled": True}
    values.update(kwargs)
    return settings.BotSettings(**values)


@contextmanager
def _world(cfg_by_book, exposure_by_book=None, holdings_by_book=None):
    client = _Client({"paper_positions": exposure_by_book or {uid: [] for uid in cfg_by_book},
                      "user_positions": holdings_by_book or {uid: [] for uid in cfg_by_book}})
    orders, notes = [], []
    bound = [None]

    @contextmanager
    def bind(uid):
        previous, bound[0] = bound[0], uid
        try:
            yield
        finally:
            bound[0] = previous

    async def equity(uid):
        return 50000.0

    async def candidate(sym):
        return {"symbol": sym, "price": 100, "yield_pct": 4, "frequency": "quarterly"}

    async def post(path, payload):
        assert path == "/v2/orders"
        assert payload["side"] == "buy"
        orders.append((bound[0], payload))
        # Stop after recording the actual submission call; do not poll a venue.
        return None, "offline test ends at submission"

    with ExitStack() as stack:
        stack.enter_context(patch.object(settings, "get_bot_settings", lambda uid: cfg_by_book[uid]))
        stack.enter_context(patch.object(allocation, "_supabase", return_value=client))
        stack.enter_context(patch.object(allocation, "effective_equity", equity))
        stack.enter_context(patch.object(accounts, "bind_for_user", bind))
        stack.enter_context(patch.object(accounts, "account_for_user", lambda uid: SimpleNamespace(account_id="primary")))
        stack.enter_context(patch.object(routes, "check_route", return_value=(True, "test")))
        stack.enter_context(patch.object(alpaca, "_post", post))
        stack.enter_context(patch.object(accumulator, "evaluate_candidate", candidate))
        stack.enter_context(patch.object(accumulator, "TIERS", {"growth": {"target": .3, "symbols": ["SCHD"]}}))
        stack.enter_context(patch.object(accumulator, "_rec", lambda symbol, reason, uid: notes.append((uid, reason))))
        yield client, orders, notes


def _buy(client, uid):
    return asyncio.run(accumulator.accumulate_for_book(client, uid))


def test_unavailable_or_disabled_settings_stop_direct_income_buy_before_any_ledger_read():
    for cfg in (settings._DEFAULTS, _cfg(auto_trade_enabled=False),
                _cfg(dividend_lt_enabled=False), _cfg(allocation_overrides={"income": 0})):
        with _world({"book-a": cfg}) as (client, orders, notes):
            assert _buy(client, "book-a") is None
            assert not orders
            assert not client.reads


def test_failed_income_exposure_read_never_reaches_direct_broker_submit():
    for unreadable in (RuntimeError("database unavailable"), None):
        with _world({"book-a": _cfg()}, {"book-a": unreadable}) as (client, orders, notes):
            assert _buy(client, "book-a") is None
            assert not orders
            assert ("paper_positions", "book-a") in client.reads
            assert any("exposure is unreadable" in reason for uid, reason in notes)


def test_unreadable_income_holdings_are_not_an_empty_sleeve():
    for unreadable in (RuntimeError("holdings unavailable"), None,
                       [{"ticker": "SCHD", "shares": "bad", "avg_cost": 100}],
                       [{"ticker": "SCHD", "shares": 100, "avg_cost": 0}]):
        with _world({"book-a": _cfg()}, holdings_by_book={"book-a": unreadable}) as (client, orders, notes):
            assert _buy(client, "book-a") is None
            assert not orders
            assert any("holdings are unreadable" in reason for uid, reason in notes)


def test_unknown_book_does_not_prevent_healthy_sibling_from_its_own_direct_buy():
    for bad_settings, bad_exposure in ((settings._DEFAULTS, []),
                                        (_cfg(), RuntimeError("one book read failed"))):
        with _world({"book-a": bad_settings, "book-b": _cfg()},
                    {"book-a": bad_exposure, "book-b": []}) as (client, orders, notes):
            _buy(client, "book-a")
            _buy(client, "book-b")
            assert len(orders) == 1 and orders[0][0] == "book-b"
            assert orders[0][1]["symbol"] == "SCHD"
            assert float(orders[0][1]["notional"]) == 1000


def test_existing_income_exposure_consumes_this_books_direct_buy_budget():
    position = {"asset_type": "stock", "strategy": "dividend_lt",
                "quantity": 99, "entry_price": 100}
    with _world({"book-a": _cfg(), "book-b": _cfg()},
                {"book-a": [position], "book-b": []}) as (client, orders, notes):
        _buy(client, "book-a")
        _buy(client, "book-b")
        assert [uid for uid, payload in orders] == ["book-b"]
        assert any(uid == "book-a" and "free $100" in reason for uid, reason in notes)


if __name__ == "__main__":
    sys.exit(run_tests(dict(vars())))
