"""Completed-day review evidence, persistence and real Discovery binding."""

from __future__ import annotations

import asyncio
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace, ModuleType
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import load_module, run_tests, stub_config

stub_config()
review = load_module("app.learning.daily_review")
NOW = datetime(2026, 9, 8, 15, tzinfo=timezone.utc)


def _settings(tmp, **changes):
    values = dict(trezo_research_enabled=True, trading_mode="paper",
                  trezo_research_db_path=str(Path(tmp) / "research.sqlite3"))
    values.update(changes)
    return SimpleNamespace(**values)


def _row(rid="a1", book="book-a", **changes):
    value = dict(id=rid, user_id=book, ticker="SPY", asset_type="stock", strategy="pattern",
                 side="long", quantity=2, entry_price=100, exit_price=102,
                 entry_at="2026-09-07T12:00:00Z", exit_at="2026-09-07T16:00:00Z",
                 status="closed_manual", realized_pnl_usd=3.8, fees_usd=0.2,
                 peak_price=110, peak_at="2026-09-07T14:00:00Z",
                 peak_unrealized_pnl_usd=20, source_payload={})
    value.update(changes)
    return value


class _Query:
    def __init__(self, client, name):
        self.client, self.name = client, name
        self.filters, self.orders, self.bounds = [], [], None

    def select(self, columns, count=None):
        if self.name == "paper_positions":
            assert columns == review.COLUMNS and count == "exact"
        return self

    def eq(self, key, value):
        self.filters.append(("eq", key, value)); return self

    def like(self, key, value):
        self.filters.append(("like", key, value)); return self

    def gte(self, key, value):
        self.filters.append(("gte", key, value)); return self

    def lt(self, key, value):
        self.filters.append(("lt", key, value)); return self

    def order(self, key, desc=False):
        self.orders.append((key, desc)); return self

    def range(self, start, end):
        self.bounds = (start, end); return self

    def execute(self):
        if self.name == "paper_accounts":
            return SimpleNamespace(data=[{"user_id": book} for book in self.client.books])
        assert self.name == "paper_positions"
        assert self.orders == [("exit_at", False), ("id", False)]
        filters = {(op, key): value for op, key, value in self.filters}
        assert len(self.filters) == 4 and filters[("like", "status")] == "closed%"
        book = filters[("eq", "user_id")]
        start, end = review._iso(filters[("gte", "exit_at")]), review._iso(filters[("lt", "exit_at")])
        rows = [r for r in self.client.rows if r["user_id"] == book
                and r["status"].startswith("closed") and start <= review._iso(r["exit_at"]) < end]
        rows.sort(key=lambda r: (r["exit_at"], r["id"]))
        self.client.calls.append((book, self.bounds))
        number = len(self.client.calls)
        if self.client.fail_page == number:
            raise RuntimeError("simulated read failure")
        offset, limit = self.bounds
        page = rows[offset:min(limit + 1, offset + self.client.cap)]
        count = len(rows)
        if self.client.mutate:
            page, count = self.client.mutate(number, page, count)
        return SimpleNamespace(data=page, count=count)


class _Client:
    def __init__(self, rows=(), cap=117, fail_page=None, mutate=None, books=("book-a",)):
        self.rows, self.calls = list(rows), []
        self.cap, self.fail_page, self.mutate, self.books = cap, fail_page, mutate, books

    def table(self, name):
        return _Query(self, name)


def _run(client, tmp, book="book-a", **changes):
    return asyncio.run(review.daily_review_for_book(client, book, settings=_settings(tmp, **changes), now=NOW))


def _day(result, day="2026-09-07"):
    receipt = next(r for r in result["reviews"] if r["accounting_day"] == day)
    return json.loads(Path(receipt["artifact_path"]).read_text(encoding="utf-8"))


def test_completed_utc_window_excludes_current_day_and_includes_exact_yesterday():
    rows = [_row(), _row("today", exit_at="2026-09-08T00:00:00Z"),
            _row("old", exit_at="2026-08-31T23:59:59Z"),
            _row("boundary", exit_at="2026-09-01T00:00:00Z")]
    with tempfile.TemporaryDirectory() as tmp:
        result = _run(_Client(rows), tmp)
        assert result["status"] == "completed" and result["history_rows_fetched"] == 2
        assert len(result["reviews"]) == 7 and result["accounting_timezone"] == "UTC"
        assert _day(result)["recorded_row_count"] == 1
        assert _day(result, "2026-09-01")["recorded_row_count"] == 1
        assert all(r["accounting_day"] < "2026-09-08" for r in result["reviews"])


def test_short_pages_continue_to_exact_count_with_book_isolation():
    rows = [_row(f"a{i:05}") for i in range(1007)] + [_row("other", "book-b", realized_pnl_usd=-9999)]
    client = _Client(rows)
    with tempfile.TemporaryDirectory() as tmp:
        result = _run(client, tmp)
        assert result["history_complete"] and result["history_rows_fetched"] == 1007
        assert [bounds[0] for _, bounds in client.calls] == list(range(0, 1007, 117))
        assert _day(result)["recorded_pnl_usd"] == 3826.6
        assert all(r["user_id"] == "book-a" for r in _day(result)["evidence"])


def test_same_sources_are_idempotent_and_late_close_creates_only_affected_revision():
    client = _Client([_row()])
    with tempfile.TemporaryDirectory() as tmp:
        first = _run(client, tmp)
        files = {str(p): p.read_bytes() for p in Path(tmp).rglob("*.json")}
        again = _run(client, tmp)
        assert first["reviews"] == again["reviews"]
        assert files == {str(p): p.read_bytes() for p in Path(tmp).rglob("*.json")}
        client.rows.append(_row("late", realized_pnl_usd=-2))
        revised = _run(client, tmp)
        assert _day(revised)["version"] == 2 and _day(first)["version"] == 1
        assert _day(revised)["recorded_pnl_usd"] == 1.8
        assert len(list(Path(tmp).rglob("*.json"))) == 8
        with closing(sqlite3.connect(revised["journal_path"])) as db:
            assert db.execute("SELECT COUNT(*) FROM daily_trade_reviews").fetchone()[0] == 8
        # Reverting source evidence reuses its earlier immutable version.
        client.rows.pop()
        reverted = _run(client, tmp)
        assert _day(reverted)["review_id"] == _day(first)["review_id"]
        with closing(sqlite3.connect(revised["journal_path"])) as db:
            current_id = db.execute("SELECT review_id FROM daily_trade_review_current WHERE book_id=? AND accounting_day=? AND schema_version=?",
                                    ("book-a", "2026-09-07", 1)).fetchone()[0]
            assert current_id == _day(first)["review_id"]
            assert db.execute("SELECT COUNT(*) FROM daily_trade_reviews").fetchone()[0] == 8


def test_failed_or_truncated_read_never_stores_partial_metrics_as_zero():
    rows = [_row(str(i)) for i in range(350)]
    clients = [_Client(rows, fail_page=1), _Client(rows, fail_page=2),
               _Client(rows, mutate=lambda n, p, c: ([], c) if n == 2 else (p, c)),
               _Client(rows, mutate=lambda n, p, c: (p, c + 1) if n == 2 else (p, c)),
               _Client(rows, mutate=lambda n, p, c: (p, None)),
               _Client(rows, mutate=lambda n, p, c: ([_row("0")] + p[1:], c) if n == 2 else (p, c))]
    for client in clients:
        with tempfile.TemporaryDirectory() as tmp:
            result = _run(client, tmp)
            assert result["status"] == "failed" and not result["history_complete"]
            assert result["reviews"] == [] and "recorded_pnl_usd" not in result
            assert not list(Path(tmp).rglob("*.sqlite3"))


def test_foreign_book_in_response_cannot_be_persisted():
    client = _Client([_row()], mutate=lambda n, p, c: ([_row(book="foreign")], c))
    with tempfile.TemporaryDirectory() as tmp:
        result = _run(client, tmp)
        assert result["status"] == "failed" and result["reviews"] == []
        assert not list(Path(tmp).rglob("*.sqlite3"))


def test_empty_complete_day_is_explicit_and_missing_pnl_is_unknown():
    with tempfile.TemporaryDirectory() as tmp:
        empty = _run(_Client(), tmp)
        assert empty["history_complete"] and _day(empty)["recorded_pnl_usd"] == 0
        missing = _run(_Client([_row(realized_pnl_usd=None)]), tmp)
        day = _day(missing)
        assert day["recorded_pnl_usd"] is None
        assert day["by_strategy"][0]["missing_pnl_count"] == 1
        assert day["verified_return"] is None and day["account_return_pct"] is None


def test_long_and_short_sampled_price_observations_are_direction_correct():
    rows = [_row(), _row("short", ticker="QQQ", side="short", entry_price=100,
                         exit_price=95, peak_price=90, peak_unrealized_pnl_usd=20)]
    with tempfile.TemporaryDirectory() as tmp:
        day = _day(_run(_Client(rows), tmp))
        observations = {e["id"]: e["observation"] for e in day["evidence"]}
        assert observations["a1"]["sampled_price_giveback_fraction"] == 0.8
        assert observations["short"]["sampled_price_giveback_fraction"] == 0.5
        assert day["sampled_peak_observation_count"] == 2
        assert day["full_intraday_mfe_mae_available"] is False
        assert day["partial_and_quantity_history"] == "unverified"
        assert day["research_hints"][0]["evidence_row_ids"] == ["a1", "short"]


def test_options_partials_missing_peaks_and_quantity_changes_stay_unknown():
    cases = [dict(asset_type="option"), dict(status="closed_partial"), dict(peak_price=None),
             dict(peak_at="2026-09-08T00:00:00Z"), dict(quantity=1),
             dict(source_payload={"merged": True}), dict(exit_price=115)]
    for changes in cases:
        with tempfile.TemporaryDirectory() as tmp:
            day = _day(_run(_Client([_row(**changes)]), tmp))
            assert day["sampled_peak_observation_count"] == 0
            assert day["evidence"][0]["observation"]["sampled_price_giveback_fraction"] is None
            assert day["research_hints"] == []


def test_related_partial_in_other_review_day_excludes_remaining_position():
    rows = [_row(), _row("slice", status="closed_partial", exit_at="2026-09-06T16:00:00Z")]
    with tempfile.TemporaryDirectory() as tmp:
        day = _day(_run(_Client(rows), tmp))
        assert day["sampled_peak_observation_count"] == 0
        assert day["evidence"][0]["observation"]["reason"] == "partial_or_complex_position"


def test_store_and_export_failure_are_visible_with_no_false_completion():
    with tempfile.TemporaryDirectory() as tmp, patch.object(review, "_save_reviews", side_effect=OSError("full")):
        result = _run(_Client([_row()]), tmp)
        assert result["status"] == "failed" and result["history_complete"]
        assert result["reason"] == "review_build_or_store_failed" and result["reviews"] == []
    with tempfile.TemporaryDirectory() as tmp, patch.object(review, "_export", side_effect=OSError("full")):
        result = _run(_Client([_row()]), tmp)
        assert result["status"] == "incomplete"
        assert Path(result["journal_path"]).exists()
        assert all(r["artifact_export_error"] == "OSError" for r in result["reviews"])


def test_disabled_or_nonpaper_review_does_no_read_or_store():
    with tempfile.TemporaryDirectory() as tmp:
        client = _Client([_row()])
        assert _run(client, tmp, trezo_research_enabled=False)["status"] == "disabled"
        assert _run(client, tmp, trading_mode="live")["status"] == "blocked"
        assert client.calls == [] and not list(Path(tmp).iterdir())


def test_real_discovery_binds_two_books_to_durable_review_before_research():
    discovery = load_module("app.agents.strategy_discovery")
    performance = load_module("app.paper.performance")
    client = _Client([_row(), _row("b1", "book-b", realized_pnl_usd=-12)], books=("book-a", "book-b"))
    research_calls = []

    async def report(*args):
        return performance.compute_performance([])

    async def no_recall(*args, **kwargs):
        return []

    async def no_remember(*args, **kwargs):
        return True

    async def no_insight(*args, **kwargs):
        return ""

    with tempfile.TemporaryDirectory() as tmp:
        cfg = _settings(tmp)
        bridge = ModuleType("app.research.bridge")

        async def research(book):
            with closing(sqlite3.connect(Path(tmp) / "daily_trade_reviews.sqlite3")) as db:
                assert db.execute("SELECT COUNT(*) FROM daily_trade_reviews WHERE book_id=?", (book,)).fetchone()[0] == 7
            research_calls.append(book)
            return {"event": "internal_research", "user_id": book, "status": "disabled"}

        bridge.research_for_book = research
        # Discovery uses its actual clock. Shift fixtures to yesterday, keeping
        # deterministic window tests above separate from this real binding test.
        yesterday = datetime.now(timezone.utc).date().toordinal() - 1
        day = datetime.fromordinal(yesterday).date().isoformat()
        for row in client.rows:
            for key in ("entry_at", "exit_at", "peak_at"):
                row[key] = day + row[key][10:]
        with patch.object(review, "get_settings", lambda: cfg), \
                patch.object(discovery, "_supabase", lambda: client), \
                patch.object(discovery, "performance_for_user", report), \
                patch.object(discovery.StrategyDiscoveryAgent, "recall", no_recall), \
                patch.object(discovery.StrategyDiscoveryAgent, "remember", no_remember), \
                patch.object(discovery.StrategyDiscoveryAgent, "_backtest_insight", no_insight), \
                patch.dict(sys.modules, {"app.research.bridge": bridge}):
            messages = asyncio.run(discovery.StrategyDiscoveryAgent().tick())
            repeated = asyncio.run(discovery.StrategyDiscoveryAgent().tick())
        results = [m.payload for m in messages if m.payload.get("event") == "daily_trade_review"]
        again = [m.payload for m in repeated if m.payload.get("event") == "daily_trade_review"]
        assert research_calls == ["book-a", "book-b", "book-a", "book-b"]
        assert len(results) == 2 and all(r["status"] == "completed" for r in results)
        assert [r["reviews"] for r in results] == [r["reviews"] for r in again]
        assert {_day(r, day)["book_id"] for r in results} == {"book-a", "book-b"}
        assert {_day(r, day)["recorded_pnl_usd"] for r in results} == {3.8, -12}
        assert all(not r["execution_enabled"] and not r["strategy_promotion_eligible"] for r in results)
        assert len(list(Path(tmp).rglob("*.json"))) == 14


if __name__ == "__main__":
    raise SystemExit(run_tests(globals()))
