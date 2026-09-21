"""Report ingestion -> per-book research and symmetric bearish accounting."""
from __future__ import annotations

import asyncio
from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import load_module, quiet_activity_log, run_tests, stub_config
stub_config()
core = load_module("app.research.core")
cycle = load_module("app.research.cycle")
opportunities = load_module("app.research.opportunities")
market_desk = load_module("app.agents.market_desk")
bridge = load_module("app.research.bridge")

CATALOG = {key: {"id": key, "implemented": True} for key in
           ("stock_long", "stock_short", "long_options", "wheel_csp", "wheel_cc", "spreads")}


@contextmanager
def patched(obj, **values):
    old = {key: getattr(obj, key) for key in values}
    try:
        for key, value in values.items():
            setattr(obj, key, value)
        yield
    finally:
        for key, value in old.items():
            setattr(obj, key, value)


def view(**overrides):
    payload = {"as_of": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
               "regime": "risk_off", "movers_down": ["AMD"], "indices": {},
               "movers_up": [], "summary": "Synthetic plumbing report, not market evidence."}
    payload.update(overrides)
    return market_desk.build_view(payload, source="test_report")


def candles(count=220, drift=-0.008):
    price, result = 100.0, []
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=count+2)
    for index in range(count):
        opening, price = price, price * (1 + drift)
        result.append({"timestamp": (start + timedelta(days=index)).isoformat(),
                       "open": opening, "close": price, "high": max(opening, price)*1.001,
                       "low": min(opening, price)*0.999})
    return result


def test_opportunities_distinguish_bearish_long_puts_from_short_stock_and_unavailable_lanes():
    catalog = {**CATALOG, "spreads": {"id": "spreads", "implemented": False,
                                      "reason": "synthetic_missing_multileg_route"}}
    rows = opportunities.build_opportunities(view(), "book-a", catalog=catalog)
    assert len(rows) == 4
    put = next(r for r in rows if r["strategy"] == "long_put")
    assert put["market_direction"] == "bearish" and put["position_side"] == "long"
    spread = next(r for r in rows if r["strategy"] == "bear_call_credit_spread")
    assert spread["capability_status"] == "unavailable"
    assert spread["capability_reason"] == "synthetic_missing_multileg_route"
    assert all(r["entry_price"] is None and r["execution_enabled"] is False for r in rows)
    assert all(r["source"] == "test_report" and r["as_of"] and r["report_id"] for r in rows)


def test_marketdesk_real_tick_persists_for_both_books_and_retry_deduplicates():
    actual = opportunities.capture_market_view
    sample = view()
    async def briefing(self):
        return {"id": "synthetic-report", "payload": {"as_of": sample.as_of,
                "regime": sample.regime, "movers_down": ["AMD"]}, "source": sample.source}
    with tempfile.TemporaryDirectory() as tmp, ExitStack() as patches:
        patches.enter_context(quiet_activity_log())
        path = Path(tmp)/"research.sqlite3"
        cfg = SimpleNamespace(trezo_research_db_path=str(path))
        async def capture(value):
            return await actual(value, settings=cfg, book_ids=["book-a", "book-b"], catalog=CATALOG)
        patches.enter_context(patched(opportunities, capture_market_view=capture))
        patches.enter_context(patched(market_desk.MarketDeskAgent, _newest_briefing=briefing))
        patches.enter_context(patched(market_desk, _current=None))
        agent = market_desk.MarketDeskAgent()
        messages = asyncio.run(agent.tick())
        receipts = [m.payload for m in messages if m.payload.get("event") == "market_opportunity_library"]
        assert {r["user_id"] for r in receipts} == {"book-a", "book-b"}
        assert all(r["opportunity_count"] == 4 for r in receipts)
        assert asyncio.run(agent.tick()) == []
        for book in ("book-a", "book-b"):
            rows = opportunities.read_opportunities(path, book)
            assert len(rows) == 4 and all(r["book_id"] == book for r in rows)
        assert opportunities.read_opportunities(path, "unknown-book") == []


def test_stale_and_future_reports_do_not_create_current_opportunities_and_history_is_retained():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp)/"research.sqlite3"
        rows = opportunities.build_opportunities(view(), "book-a", catalog=CATALOG)
        opportunities.save_opportunities(path, "book-a", rows)
        later = datetime.now(timezone.utc)+timedelta(days=2)
        assert opportunities.read_opportunities(path, "book-a", now=later) == []
        history = opportunities.read_opportunities(path, "book-a", now=later, include_expired=True)
        assert len(history) == 4 and not any(r["fresh"] for r in history)
        for days in (-2, 2):
            sample = view(as_of=(datetime.now(timezone.utc)+timedelta(days=days)).isoformat())
            assert opportunities.build_opportunities(sample, "book-a", catalog=CATALOG) == []


def test_unimplemented_capabilities_are_retained_as_code_reference_not_report_claims():
    catalog = {**CATALOG,
               "crypto_short": {"id": "crypto_short", "implemented": False,
                                  "reason": "no_borrowing_adapter"},
               "forex": {"id": "forex", "implemented": False,
                          "reason": "no_execution_venue"}}
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp)/"research.sqlite3"
        rows = opportunities.build_opportunities(view(), "book-a", catalog=catalog)
        opportunities.save_opportunities(path, "book-a", rows, catalog=catalog)
        reference = opportunities.read_capability_reference(path)
        assert reference["source"] == "trezo_repository_capability_catalog"
        assert reference["evidence_type"] == "implementation_reference_not_report_signal"
        assert {r["id"] for r in reference["capabilities"]} >= {"crypto_short", "forex"}
        assert "book_id" not in reference and "report_id" not in reference
        assert not any(r["capability_id"] in {"crypto_short", "forex"} for r in rows)


def test_daily_context_freezes_own_symbol_and_does_not_accept_foreign_performance():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp)/"research.sqlite3"
        for book, ticker in (("book-a", "AMD"), ("book-b", "QQQ")):
            rows = opportunities.build_opportunities(view(movers_down=[ticker]), book, catalog=CATALOG)
            opportunities.save_opportunities(path, book, rows)
        ctx = opportunities.daily_context(path, "book-a", performance={"book_id": "book-a", "total_realized_usd": -15})
        assert ctx["symbol"] == "AMD" and ctx["performance"]["total_realized_usd"] == -15
        assert opportunities.daily_context(path, "book-b")["symbol"] == "QQQ"
        rows = opportunities.build_opportunities(view(movers_down=["SPY"]), "book-a", catalog=CATALOG)
        opportunities.save_opportunities(path, "book-a", rows)
        assert opportunities.daily_context(path, "book-a") == ctx
        try:
            opportunities.daily_context(path, "book-a", performance={"book_id": "book-b"})
            raise AssertionError("foreign evidence accepted")
        except ValueError:
            pass


def test_library_drives_real_research_symbol_and_all_candidates_remain_nonexecuting():
    calls = []
    async def fetch(symbol, asset_type):
        calls.append((symbol, asset_type))
        return [SimpleNamespace(**{**row, "timestamp": datetime.fromisoformat(row["timestamp"])})
                for row in candles()]
    with tempfile.TemporaryDirectory() as tmp, patched(bridge, _fetch_daily=fetch, _DATA_CACHE={}):
        path = Path(tmp)/"research.sqlite3"
        rows = opportunities.build_opportunities(view(), "book-a", catalog=CATALOG)
        opportunities.save_opportunities(path, "book-a", rows)
        settings = SimpleNamespace(trezo_research_enabled=True, trading_mode="paper",
            trezo_research_db_path=str(path), trezo_research_symbol="SPY",
            trezo_research_asset_type="stock", trezo_research_capital_mode="fixed_scenario",
            trezo_research_capitals="1000", trezo_research_commission_bps=2,
            trezo_research_slippage_bps=5)
        result = asyncio.run(bridge.research_for_book("book-a", settings=settings,
            book_evidence={"book_id": "book-a", "performance": {"book_id": "book-a"},
                           "risk_state": {"book_id": "book-a", "trading_halted": True}}))
        assert result["status"] == "completed", result
        assert calls == [("AMD", "stock")]
        assert result["cases"][0]["opportunity_ids"]
        assert result["cases"][0]["directions_tested"] == ["long", "short"]
        assert result["execution_enabled"] is False


def test_short_replay_profits_on_decline_and_marked_equity_subtracts_liability():
    bars = core.normalize_candles(candles())
    candidate = core.Candidate("book-a", "AMD", "breakdown_low", direction="short")
    assumption = core.Assumptions(1000, 10, 5)
    result = core.replay(bars, candidate, assumption, start=0, end=len(bars), phase="train")
    assert result["net_pnl_usd"] > 0 and result["trades"] > 0
    assert all(t["direction"] == "short" and t["entry_price"] > t["exit_price"] for t in result["trade_log"])
    assert abs(result["net_pnl_usd"] - sum(t["net_pnl_usd"] for t in result["trade_log"])) < 1e-8
    for row in result["equity_curve"]:
        assert abs(row["equity"] - (row["cash"]+row["position_qty"]*bars[row["index"]]["close"])) < 1e-8
    assert any(row["position_qty"] < 0 for row in result["equity_curve"])


def test_short_gap_stop_is_adverse_and_continuation_keeps_opposite_direction():
    bars = core.normalize_candles(candles())
    candidate = core.Candidate("book-a", "AMD", "breakdown_low", direction="short")
    assumptions = core.Assumptions(1000, 0, 0)
    # First entry at bar 20 after bar 19's close; next bar gaps over short stop.
    bars[21].update(open=110.0, high=111.0, low=109.0, close=110.0)
    result = core.replay(bars, candidate, assumptions, start=0, end=len(bars), phase="train")
    assert result["trade_log"][0]["exit_reason"] == "gap_stop"
    assert result["trade_log"][0]["exit_price"] == 110.0
    assert result["trade_log"][0]["net_pnl_usd"] < 0
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp)/"research.sqlite3"
        for day in ("first", "second"):
            outcome = cycle.run_cycle(path, book_id="book-a", symbol="AMD", candles=candles(),
                         starting_capital=1000, commission_bps=2, slippage_bps=5, cycle_key=day)
            assert outcome["status"] == "completed", outcome
            assert {t["spec"]["direction"] for t in outcome["trials"]} == {"long", "short"}


if __name__ == "__main__":
    raise SystemExit(run_tests(globals()))
