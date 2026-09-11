"""Per-book, durable market-report hypotheses; never an execution queue.

A report supplies observed movers and direction, not an entry quote or an
attested trade. Capabilities record what still needs verification. Historical
research reads a frozen daily selection from THIS book's journal only.
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re

from .core import canonical, digest
from .store import Store

SCHEMA = """
CREATE TABLE IF NOT EXISTS market_opportunities (
 opportunity_id TEXT PRIMARY KEY, book_id TEXT NOT NULL, report_id TEXT NOT NULL,
 as_of TEXT NOT NULL, expires_at TEXT NOT NULL, payload_json TEXT NOT NULL,
 UNIQUE(book_id, report_id, opportunity_id)
);
CREATE INDEX IF NOT EXISTS market_opportunities_book_time
 ON market_opportunities(book_id, as_of DESC);
CREATE TABLE IF NOT EXISTS research_daily_opportunity_context (
 book_id TEXT NOT NULL, accounting_day TEXT NOT NULL, payload_json TEXT NOT NULL,
 PRIMARY KEY(book_id, accounting_day)
);
CREATE TABLE IF NOT EXISTS market_capability_catalog (
 catalog_hash TEXT PRIMARY KEY, observed_at TEXT NOT NULL, payload_json TEXT NOT NULL
);
"""


def journal_path(settings) -> Path:
    configured = str(getattr(settings, "trezo_research_db_path", "") or "")
    return (Path(configured).expanduser() if configured else
            Path(__file__).resolve().parents[2] / "local_state" / "research.sqlite3")


def _stamp(value):
    stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("opportunity timestamp requires timezone")
    return stamp.astimezone(timezone.utc)


def _capabilities():
    from app.runtime.capabilities import capability_catalog
    return {row["id"]: row for row in capability_catalog()}


def build_opportunities(view, book_id, *, catalog=None) -> list[dict]:
    """Derive labeled hypotheses solely from explicit report movers/indices."""
    if not isinstance(book_id, str) or not book_id.strip() or len(book_id) > 128:
        raise ValueError("explicit bounded book required")
    if not view.fresh():
        return []
    report = asdict(view)
    source_id = digest(report)
    observed = _stamp(view.as_of)
    expires = observed + timedelta(seconds=view.max_age_seconds)
    catalog = _capabilities() if catalog is None else catalog
    evidence = {}
    for ticker in view.movers_up:
        evidence.setdefault((ticker, "bullish"), []).append("report_movers_up")
    for ticker in view.movers_down:
        evidence.setdefault((ticker, "bearish"), []).append("report_movers_down")
    for ticker, move in view.indices.items():
        if move != 0:
            evidence.setdefault((ticker, "bullish" if move > 0 else "bearish"), []).append(
                "reported_index_change")
    out = []
    for (ticker, direction), basis in sorted(evidence.items()):
        if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", ticker):
            continue
        variants = ([("stock", "long", "breakout_high", "stock_long"),
                     ("option", "long", "long_call", "long_options"),
                     ("option", "short", "cash_secured_put", "wheel_csp")]
                    if direction == "bullish" else
                    [("stock", "short", "breakdown_low", "stock_short"),
                     ("option", "long", "long_put", "long_options"),
                     ("option_spread", "multi_leg", "bear_call_credit_spread", "spreads"),
                     ("option", "short", "covered_call", "wheel_cc")])
        for instrument, position_side, strategy, capability_id in variants:
            capability = catalog.get(capability_id, {})
            implemented = capability.get("implemented") is True
            reason = ("fresh_quote_signal_and_per_book_risk_approval_required" if implemented
                      else str(capability.get("reason") or "capability_not_implemented_or_unknown"))
            requirements = ["fresh_executable_market_data", "own_book_risk_approval"]
            if capability_id == "stock_short":
                requirements += ["broker_shortable_asset", "borrow_availability", "margin_permission"]
            if instrument.startswith("option"):
                requirements += ["broker_options_permission", "valid_contract_and_quote"]
            if capability_id == "wheel_cc":
                requirements += ["unencumbered_100_shares_per_contract_in_same_book"]
            if capability_id in {"wheel_csp", "spreads"}:
                requirements += ["same_book_collateral_or_defined_risk_buying_power"]
            body = {"book_id": book_id, "report_id": source_id,
                    "source": view.source, "as_of": observed.isoformat(),
                    "expires_at": expires.isoformat(), "context_kind": view.context_kind,
                    "provenance": view.provenance, "ticker": ticker,
                    "market_direction": direction, "position_side": position_side,
                    "instrument": instrument, "strategy": strategy,
                    "capability_id": capability_id,
                    "capability_status": "unverified" if implemented else "unavailable",
                    "capability_reason": reason, "requirements": requirements,
                    "evidence_basis": basis, "regime": view.regime,
                    "reported_index_change": view.indices.get(ticker),
                    "catalysts": view.catalysts, "report_summary": view.summary,
                    "hypothesis": "Evaluate a fresh directional setup; report movement alone is not an entry signal.",
                    "evidence_type": "inferred_research_hypothesis_from_report",
                    "execution_enabled": False, "entry_price": None,
                    "strategy_promotion_eligible": False}
            out.append({**body, "opportunity_id": digest(body)})
    return out[:192]


def save_opportunities(path, book_id, rows, *, catalog=None):
    store = Store(path)
    with store.connection() as connection:
        connection.executescript(SCHEMA)
        connection.execute("BEGIN IMMEDIATE")
        if catalog is not None:
            # Shared implementation facts have no account state and are NOT
            # falsely attributed to the market report that triggered capture.
            reference = {"source": "trezo_repository_capability_catalog",
                         "evidence_type": "implementation_reference_not_report_signal",
                         "capabilities": list(catalog.values()),
                         "broker_permission_verified": False}
            connection.execute("INSERT OR IGNORE INTO market_capability_catalog VALUES (?,?,?)",
                (digest(reference), datetime.now(timezone.utc).isoformat(), canonical(reference)))
        inserted = 0
        for row in rows:
            if row.get("book_id") != book_id:
                raise ValueError("opportunity belongs to another book")
            cursor = connection.execute("""INSERT OR IGNORE INTO market_opportunities
             VALUES (?,?,?,?,?,?)""", (row["opportunity_id"], book_id, row["report_id"],
                                       row["as_of"], row["expires_at"], canonical(row)))
            inserted += cursor.rowcount
    return inserted


def read_capability_reference(path):
    if not Path(path).exists():
        return None
    with Store(path).connection() as connection:
        connection.executescript(SCHEMA)
        row = connection.execute("""SELECT payload_json FROM market_capability_catalog
         ORDER BY observed_at DESC, catalog_hash DESC LIMIT 1""").fetchone()
    return json.loads(row["payload_json"]) if row else None


def read_opportunities(path, book_id, *, now=None, include_expired=False, limit=96):
    """Explicitly scoped historical or current library. Missing is an empty journal."""
    if not book_id or not 1 <= limit <= 192:
        raise ValueError("bounded per-book opportunity read required")
    if not Path(path).exists():
        return []
    store = Store(path)
    current = now or datetime.now(timezone.utc)
    with store.connection() as connection:
        connection.executescript(SCHEMA)
        rows = connection.execute("""SELECT payload_json FROM market_opportunities
         WHERE book_id=? ORDER BY as_of DESC, opportunity_id LIMIT ?""", (book_id, limit)).fetchall()
    result = []
    for raw in rows:
        row = json.loads(raw["payload_json"])
        fresh = _stamp(row["as_of"]) <= current <= _stamp(row["expires_at"])
        if fresh or include_expired:
            result.append({**row, "fresh": fresh})
    return result


def daily_context(path, book_id, *, now=None, performance=None, risk_state=None):
    """Freeze one report-derived symbol and the book's evidence per UTC day.

    No foreign book's context is accepted; recorded P&L is a review hint and
    never changes capital, thresholds, or statistical validation outcomes.
    """
    current = now or datetime.now(timezone.utc)
    if not Path(path).exists():
        return None
    store = Store(path)
    day = current.astimezone(timezone.utc).date().isoformat()
    for value in (performance, risk_state):
        if value is not None and value.get("book_id") != book_id:
            raise ValueError("research evidence belongs to another book")
    opportunities = read_opportunities(path, book_id, now=current)
    capability_reference = read_capability_reference(path)
    # Retain unavailable derivatives in the library; the OHLC pilot can
    # evaluate directional stock hypotheses, not invent option price paths.
    stocks = [row for row in opportunities if row["instrument"] == "stock"]
    with store.connection() as connection:
        connection.executescript(SCHEMA)
        connection.execute("BEGIN IMMEDIATE")
        prior = connection.execute("""SELECT payload_json FROM research_daily_opportunity_context
         WHERE book_id=? AND accounting_day=?""", (book_id, day)).fetchone()
        if prior:
            return json.loads(prior["payload_json"])
        if not stocks:
            return None
        choice = stocks[0]
        selected = [row for row in opportunities if row["ticker"] == choice["ticker"]][:12]
        body = {"book_id": book_id, "observed_at": current.isoformat(),
                "selection_method": "newest_report_then_stable_opportunity_id",
                "symbol": choice["ticker"], "asset_type": "stock",
                "opportunities": selected, "performance": performance,
                "risk_state": risk_state, "execution_enabled": False,
                "capability_reference": capability_reference,
                "research_questions": _research_questions(performance, risk_state),
                "historical_screen_does_not_validate_report_timing": True}
        connection.execute("INSERT INTO research_daily_opportunity_context VALUES (?,?,?)",
                           (book_id, day, canonical(body)))
        return body


def _research_questions(performance, risk_state):
    questions = ["Compare predeclared bullish and bearish rules on independent price evidence."]
    if performance and performance.get("history_complete") is True:
        for strategy in (performance.get("by_strategy") or [])[:20]:
            pnl = strategy.get("total_pnl_usd")
            if isinstance(pnl, (float, int)) and not isinstance(pnl, bool) and pnl < 0:
                questions.append("Review this book's recorded losses in " +
                                 str(strategy.get("strategy") or "unknown")[:80] +
                                 "; compare entry and exit variants without treating recorded losses as a proven cause.")
    if risk_state and risk_state.get("trading_halted") is True:
        questions.append("This book has a persisted halt; continue research only and retain the reason for review.")
    return questions


async def capture_market_view(view, *, settings=None, book_ids=None, catalog=None):
    """MarketDesk's direct ingest binding; each book receives its own journal rows."""
    from app.config import get_settings
    from app.brokers.accounts import load_accounts
    cfg = settings if settings is not None else get_settings()
    books = book_ids if book_ids is not None else [a.account_key for a in load_accounts()]
    receipts = []
    for book_id in dict.fromkeys(books):
        try:
            reference = _capabilities() if catalog is None else catalog
            rows = build_opportunities(view, book_id, catalog=reference)
            inserted = await asyncio.to_thread(save_opportunities, journal_path(cfg), book_id, rows,
                                               catalog=reference)
            if inserted:
                receipts.append({"event": "market_opportunity_library", "user_id": book_id,
                                 "status": "recorded", "as_of": view.as_of,
                                 "report_id": rows[0]["report_id"] if rows else None,
                                 "opportunity_count": inserted,
                                 "bearish_count": sum(r["market_direction"] == "bearish" for r in rows),
                                 "execution_enabled": False,
                                 "note": "Market-report possibilities retained for this book; fresh signals and risk approval still required.",
                                 "opportunities": [{key: row[key] for key in
                                      ("opportunity_id", "ticker", "market_direction", "position_side",
                                       "instrument", "strategy", "capability_status", "capability_reason")}
                                     for row in rows]})
        except Exception as exc:
            receipts.append({"event": "market_opportunity_library", "user_id": book_id,
                             "status": "failed", "reason": "opportunity_capture_failed",
                             "error_type": type(exc).__name__, "execution_enabled": False})
    return receipts
