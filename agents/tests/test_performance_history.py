"""Recorded performance must not turn a partial read into complete evidence.

Exercises real query pagination and the discovery tick using only local
fakes; no fixtures, credentials, runtime bootstrap or network.
"""

from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import load_module, run_tests, stub_config  # noqa: E402

performance = load_module("app.paper.performance")


def _rows(count, user="book-a", pnl=1):
    return [{"id": f"{user}-{i:06}", "user_id": user, "strategy": "example",
             "realized_pnl_usd": pnl, "status": "closed_manual",
             "exit_at": "2026-09-08T12:00:00Z"} for i in range(count)]


class _Query:
    def __init__(self, client, table):
        self.client, self.table_name = client, table
        self.filters, self.orders = [], []
        self.bounds = None
        self.count_mode = None

    def select(self, columns, count=None):
        self.count_mode = count
        return self

    def eq(self, key, value):
        self.filters.append(("eq", key, value))
        return self

    def neq(self, key, value):
        self.filters.append(("neq", key, value))
        return self

    def order(self, key, desc=False):
        self.orders.append((key, desc))
        return self

    def range(self, start, end):
        self.bounds = (start, end)
        return self

    def execute(self):
        if self.table_name == "paper_accounts":
            return types.SimpleNamespace(data=[{"user_id": u} for u in self.client.users])
        assert self.table_name == "paper_positions"
        assert self.count_mode == "exact"
        assert self.bounds is not None
        assert self.orders == [("exit_at", False), ("id", False)]
        users = [v for op, k, v in self.filters if op == "eq" and k == "user_id"]
        assert len(users) == 1, "every page must bind exactly one book"
        assert ("neq", "status", "open") in self.filters
        user = users[0]
        self.client.calls.append((user, self.bounds))
        number = sum(1 for u, _ in self.client.calls if u == user)
        if self.client.fail_pages.get(user) == number:
            raise RuntimeError("read failed")
        rows = [r for r in self.client.rows if r["user_id"] == user and r["status"] != "open"]
        rows.sort(key=lambda r: (r["exit_at"], r["id"]))
        start, end = self.bounds
        page = rows[start:min(end + 1, start + self.client.server_cap)]
        count = len(rows)
        if self.client.mutate_response:
            page, count = self.client.mutate_response(number, page, count)
        return types.SimpleNamespace(data=page, count=count)


class _Client:
    def __init__(self, rows=(), *, server_cap=117, users=("book-a",),
                 fail_pages=None, mutate_response=None):
        self.rows = list(rows)
        self.server_cap, self.users = server_cap, users
        self.fail_pages = fail_pages or {}
        self.mutate_response = mutate_response
        self.calls = []

    def table(self, name):
        return _Query(self, name)


def test_real_reader_paginates_past_server_cap_with_stable_book_filter():
    rows = _rows(1007) + _rows(12, user="book-b", pnl=-1000)
    rows.append({**_rows(1)[0], "id": "open", "status": "open"})
    client = _Client(list(reversed(rows)))
    report = asyncio.run(performance.performance_for_user(client, "book-a"))
    assert report.history_complete is True
    assert report.history_read_status == "complete"
    assert report.total_trades == report.recorded_closed_row_count == 1007
    assert report.total_realized_usd == 1007
    assert report.history_rows_fetched == 1007
    assert [bounds[0] for _, bounds in client.calls] == list(range(0, 1007, 117))
    assert report.metric_basis == "recorded_closed_position_rows"
    assert report.fee_treatment == "mixed_or_unverified"
    assert report.account_return_pct is None
    assert report.strategy_performance_verified is False
    assert report.strategy_promotion_eligible is False


def test_middle_page_failure_does_not_publish_partial_metrics():
    client = _Client(_rows(350), fail_pages={"book-a": 2})
    report = asyncio.run(performance.performance_for_user(client, "book-a"))
    assert report.history_read_status == "incomplete"
    assert report.history_rows_fetched == 117
    assert report.history_complete is False
    assert report.total_trades == report.total_realized_usd == 0
    assert report.by_strategy == [] and report.review_due is False


def test_complete_empty_history_differs_from_failed_or_unconfigured_read():
    empty = asyncio.run(performance.performance_for_user(_Client(), "book-a"))
    failed = asyncio.run(performance.performance_for_user(
        _Client(fail_pages={"book-a": 1}), "book-a"))
    absent = asyncio.run(performance.performance_for_user(None, "book-a"))
    assert empty.history_read_status == "complete" and empty.history_complete
    assert failed.history_read_status == "failed" and not failed.history_complete
    assert absent.history_read_status == "not_configured" and not absent.history_complete
    assert all(r.total_trades == 0 for r in (empty, failed, absent))


def test_premature_empty_page_is_explicitly_incomplete():
    client = _Client(_rows(350), mutate_response=lambda n, p, c: ([], c) if n == 2 else (p, c))
    report = asyncio.run(performance.performance_for_user(client, "book-a"))
    assert report.history_read_status == "incomplete"
    assert report.history_rows_fetched == 117
    assert report.total_realized_usd == 0


def test_changed_count_or_duplicate_id_cannot_claim_complete_history():
    first = _rows(1)[0]
    mutations = [
        lambda n, p, c: (p, c + 1) if n == 2 else (p, c),
        lambda n, p, c: ([first] + p[1:], c) if n == 2 else (p, c),
    ]
    for mutate in mutations:
        report = asyncio.run(performance.performance_for_user(
            _Client(_rows(350), mutate_response=mutate), "book-a"))
        assert report.history_read_status == "incomplete"
        assert report.history_complete is False and report.total_trades == 0


def test_missing_exact_count_is_not_interpreted_as_complete_empty_data():
    report = asyncio.run(performance.performance_for_user(
        _Client(mutate_response=lambda n, p, c: (p, None)), "book-a"))
    assert report.history_read_status == "incomplete"
    assert report.history_complete is False


def test_discovery_tick_binds_metadata_and_suppresses_failed_book_hints():
    stub_config()
    discovery = load_module("app.agents.strategy_discovery")
    client = _Client(_rows(25, pnl=-2) + _rows(25, user="book-b", pnl=-3),
                     users=("book-a", "book-b"), fail_pages={"book-b": 1})
    agent = discovery.StrategyDiscoveryAgent()
    remembered = []

    async def recall(**kwargs):
        return []

    async def remember(**kwargs):
        remembered.append(kwargs)

    async def no_backtests(_client):
        return ""

    async def no_research(user_id):
        return {"event": "internal_research", "user_id": user_id, "status": "disabled"}

    agent.recall, agent.remember = recall, remember
    agent._backtest_insight = no_backtests
    bridge = types.ModuleType("app.research.bridge")
    bridge.research_for_book = no_research
    with patch.object(discovery, "_supabase", lambda: client), \
            patch.dict(sys.modules, {"app.research.bridge": bridge}):
        messages = asyncio.run(agent.tick())
    metrics = {m.payload["user_id"]: m for m in messages if m.kind == "metrics"}
    good, failed = metrics["book-a"], metrics["book-b"]
    assert good.payload["history_complete"] is True
    assert good.payload["review_due"] is True
    assert good.payload["weakest_strategy"] == "example"
    assert failed.payload["history_read_status"] == "failed"
    assert failed.payload["weakest_strategy"] is None
    assert failed.payload["review_due"] is False
    assert [m.payload["user_id"] for m in messages if m.kind == "alert"] == ["book-a"]
    for message in (good, failed):
        assert message.confidence == 0
        assert message.payload["metric_basis"] == "recorded_closed_position_rows"
        assert message.payload["fee_treatment"] == "mixed_or_unverified"
        assert message.payload["account_return_pct"] is None
        assert message.payload["strategy_promotion_eligible"] is False
    assert len(remembered) == 1
    assert "unverified" in remembered[0]["content"]


if __name__ == "__main__":
    sys.exit(run_tests(dict(globals())))
