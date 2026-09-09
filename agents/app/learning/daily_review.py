"""Evidence-qualified reviews of the last seven completed UTC accounting days.

This pilot reads recorded closes, persists versioned internal research hints,
and returns receipts to Discovery. It cannot change a trading rule or place an
order. Stored peaks are sampled observations, never a complete intraday path.
"""

from __future__ import annotations

import asyncio
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import tempfile

from app.config import get_settings

SCHEMA_VERSION = 1
PAGE_SIZE = 500
MAX_ROWS = 100_000
REVIEW_DAYS = 7
COLUMNS = ("id,user_id,ticker,asset_type,strategy,side,quantity,entry_price,"
           "exit_price,entry_at,exit_at,status,realized_pnl_usd,fees_usd,"
           "peak_price,peak_at,peak_unrealized_pnl_usd,source_payload")
QUALIFICATIONS = {
    "metric_basis": "recorded_closed_position_rows",
    "account_return_pct": None,
    "verified_return": None,
    "fee_treatment": "mixed_or_unverified",
    "partial_and_quantity_history": "unverified",
    "independent_trade_count": None,
    "full_intraday_mfe_mae_available": False,
    "open_position_pnl_included": False,
    "execution_enabled": False,
    "strategy_promotion_eligible": False,
    "strategy_performance_verified": False,
    "hints_are_research_hypotheses": True,
    "research_hints_automatically_retested": False,
}


def _iso(value):
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if result.tzinfo is None or result.utcoffset() is None:
            return None
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (ValueError, TypeError, OverflowError):
        return None


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


async def _read_rows(client, book_id, start, end):
    """Complete the bounded read or return no metrics from partial evidence."""
    rows, seen, expected = [], set(), None
    while True:
        offset = len(rows)

        def query():
            return (client.table("paper_positions").select(COLUMNS, count="exact")
                    .eq("user_id", book_id).like("status", "closed%")
                    .gte("exit_at", start.isoformat()).lt("exit_at", end.isoformat())
                    .order("exit_at", desc=False).order("id", desc=False)
                    .range(offset, offset + PAGE_SIZE - 1).execute())

        try:
            response = await asyncio.to_thread(query)
        except Exception:
            return None, {"history_read_status": "failed" if not rows else "incomplete",
                          "history_rows_fetched": len(rows), "reason": "history_read_failed"}
        page, count = getattr(response, "data", None), getattr(response, "count", None)
        reason = None
        if (not isinstance(page, list) or not isinstance(count, int)
                or isinstance(count, bool) or count < 0):
            reason = "invalid_history_response"
        elif expected is not None and count != expected:
            reason = "history_changed_during_read"
        elif count > MAX_ROWS:
            reason = "history_limit_exceeded"
        else:
            expected = count
            for row in page:
                rid = row.get("id") if isinstance(row, dict) else None
                closed = _iso(row.get("exit_at")) if isinstance(row, dict) else None
                if (not isinstance(rid, str) or not rid or rid in seen
                        or row.get("user_id") != book_id
                        or not str(row.get("status", "")).startswith("closed")
                        or closed is None or not start <= closed < end):
                    reason = "invalid_or_repeated_history_row"
                    break
                seen.add(rid)
                rows.append(row)
            if not reason and (len(rows) > expected or (not page and len(rows) != expected)):
                reason = "history_count_mismatch"
        if reason:
            return None, {"history_read_status": "incomplete", "history_rows_fetched": len(rows),
                          "reason": reason}
        if len(rows) == expected:
            return rows, {"history_read_status": "complete", "history_rows_fetched": len(rows),
                          "read_consistency": "paginated_not_transaction_snapshot"}


def _position_signature(row):
    return (row.get("ticker"), row.get("side"), row.get("entry_at"), row.get("strategy"))


def _sampled_giveback(row, related_partial):
    """A price-only observation; quantity provenance remains explicitly unknown."""
    unknown = {"sampled_price_giveback_fraction": None, "sampled_peak_gain_fraction": None,
               "observation_status": "unknown"}
    if row.get("asset_type") not in {"stock", "crypto"}:
        return {**unknown, "reason": "unsupported_asset"}
    payload = row.get("source_payload") or {}
    if not isinstance(payload, dict):
        return {**unknown, "reason": "invalid_provenance"}
    complex_keys = ("partial", "partial_close", "trim", "merged", "merge_count",
                    "parent_position_id", "adopted", "adopted_from_broker")
    if (row.get("status") in {"closed_partial", "closed_adopted", "closed_assigned", "closed_expired"}
            or related_partial or any(payload.get(key) for key in complex_keys)):
        return {**unknown, "reason": "partial_or_complex_position"}
    entry, exit_price, peak, qty, peak_pnl = [_number(row.get(key)) for key in
        ("entry_price", "exit_price", "peak_price", "quantity", "peak_unrealized_pnl_usd")]
    if any(v is None or v <= 0 for v in (entry, exit_price, peak, qty, peak_pnl)):
        return {**unknown, "reason": "missing_or_invalid_peak_evidence"}
    opened, peaked, closed = [_iso(row.get(key)) for key in ("entry_at", "peak_at", "exit_at")]
    if opened is None or peaked is None or closed is None or not opened <= peaked <= closed:
        return {**unknown, "reason": "peak_outside_holding_window"}
    side = row.get("side")
    if side not in {"long", "short"}:
        return {**unknown, "reason": "invalid_side"}
    direction = 1 if side == "long" else -1
    peak_move = direction * (peak - entry)
    exit_move = direction * (exit_price - entry)
    # Trims and merged entry bases can leave an earlier dollar peak attached
    # to a different position size. Do not diagnose those mismatched records.
    if peak_move <= 0 or not math.isclose(qty * peak_move, peak_pnl, rel_tol=0.005, abs_tol=0.01):
        return {**unknown, "reason": "peak_quantity_or_basis_inconsistent"}
    if exit_move > peak_move + max(1e-8, abs(peak_move) * 0.0001):
        return {**unknown, "reason": "exit_exceeds_sampled_peak"}
    return {"sampled_price_giveback_fraction": round(max(0.0, (peak_move - exit_move) / peak_move), 6),
            "sampled_peak_gain_fraction": round(peak_move / entry, 6),
            "observation_status": "sampled_price_only",
            "reason": "observed_peak_not_full_intraday_path"}


def _build_day(book_id, day, rows, partial_signatures):
    evidence, groups, hints = [], {}, []
    for row in rows:
        related_partial = _position_signature(row) in partial_signatures
        record = {key: row.get(key) for key in COLUMNS.split(",") if key != "source_payload"}
        # Keep signal payloads out of exported research files. A hash detects
        # revisions while selected observations carry their explicit reasons.
        record["source_payload_hash"] = _hash(row.get("source_payload"))
        record["related_partial_in_review_window"] = related_partial
        record["observation"] = _sampled_giveback(row, related_partial)
        evidence.append(record)
        strategy = str(row.get("strategy") or "unknown")
        group = groups.setdefault(strategy, {"strategy": strategy, "row_ids": [], "pnls": [],
                                            "missing_pnl_count": 0, "partial_row_count": 0})
        group["row_ids"].append(row["id"])
        pnl = _number(row.get("realized_pnl_usd"))
        if pnl is None:
            group["missing_pnl_count"] += 1
        else:
            group["pnls"].append(pnl)
        group["partial_row_count"] += int(row.get("status") == "closed_partial")
    strategies = []
    for strategy, group in sorted(groups.items()):
        pnls = group.pop("pnls")
        row_ids = group.pop("row_ids")
        pnl = round(sum(pnls), 4) if not group["missing_pnl_count"] else None
        strategies.append({**group, "recorded_row_count": len(row_ids),
                           "positive_recorded_rows": sum(p > 0 for p in pnls),
                           "negative_recorded_rows": sum(p < 0 for p in pnls),
                           "recorded_pnl_usd": pnl})
        if pnl is not None and pnl < 0:
            hints.append({"kind": "review_negative_recorded_pnl", "strategy": strategy,
                          "evidence_row_ids": row_ids,
                          "hypothesis": "Compare predeclared entry and exit variants on independent data; recorded loss alone does not identify its cause."})
        gave_back = [e["id"] for e in evidence if str(e.get("strategy") or "unknown") == strategy
                     and (e["observation"]["sampled_price_giveback_fraction"] or 0) >= 0.5]
        if gave_back:
            hints.append({"kind": "compare_profit_protection", "strategy": strategy,
                          "evidence_row_ids": gave_back,
                          "hypothesis": "Compare a predeclared trailing or partial-exit rule with the original rule using covered price paths and costs; the sampled peak is hindsight."})
    source_hash = _hash(evidence)
    return {**QUALIFICATIONS, "schema_version": SCHEMA_VERSION, "book_id": book_id,
            "accounting_day": day, "accounting_timezone": "UTC", "source_hash": source_hash,
            "recorded_row_count": len(rows), "by_strategy": strategies,
            "recorded_pnl_usd": (round(sum(s["recorded_pnl_usd"] for s in strategies), 4)
                                 if all(s["recorded_pnl_usd"] is not None for s in strategies) else None),
            "sampled_peak_observation_count": sum(e["observation"]["observation_status"] == "sampled_price_only" for e in evidence),
            "evidence": evidence, "research_hints": hints,
            "limitations": ["Closed rows can represent partial slices or bookkeeping events, not independent round trips.",
                            "Internal partial outcomes absent from paper_positions are not included or estimated.",
                            "No broker reconciliation, complete quantity history, fees audit, open NAV or cash-flow return.",
                            "Peaks sample available prices; missing paths, MAE and post-exit opportunity remain unknown.",
                            "Hints are retained for research review; they do not alter risk rules or promote strategies."]}


def _save_reviews(path, reviews):
    path.parent.mkdir(parents=True, exist_ok=True)
    saved = []
    # sqlite's context manager only commits; closing is needed on Windows.
    with closing(sqlite3.connect(path, timeout=10)) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("""CREATE TABLE IF NOT EXISTS daily_trade_reviews (
            review_id TEXT PRIMARY KEY, book_id TEXT NOT NULL, accounting_day TEXT NOT NULL,
            schema_version INTEGER NOT NULL, source_hash TEXT NOT NULL, version INTEGER NOT NULL,
            payload TEXT NOT NULL, UNIQUE(book_id, accounting_day, schema_version, source_hash))""")
        db.execute("""CREATE TABLE IF NOT EXISTS daily_trade_review_current (
            book_id TEXT NOT NULL, accounting_day TEXT NOT NULL, schema_version INTEGER NOT NULL,
            review_id TEXT NOT NULL REFERENCES daily_trade_reviews(review_id), observed_at TEXT NOT NULL,
            PRIMARY KEY(book_id, accounting_day, schema_version))""")
        db.commit()
        db.execute("BEGIN IMMEDIATE")
        try:
            for review in reviews:
                scope = (review["book_id"], review["accounting_day"], SCHEMA_VERSION)
                old = db.execute("SELECT payload FROM daily_trade_reviews WHERE book_id=? AND accounting_day=? AND schema_version=? AND source_hash=?",
                                 (*scope, review["source_hash"])).fetchone()
                if old:
                    item = json.loads(old[0])
                else:
                    version = db.execute("SELECT COALESCE(MAX(version), 0)+1 FROM daily_trade_reviews WHERE book_id=? AND accounting_day=? AND schema_version=?", scope).fetchone()[0]
                    item = {**review, "version": version,
                            "review_id": _hash([*scope, review["source_hash"]]),
                            "created_at": datetime.now(timezone.utc).isoformat()}
                    db.execute("INSERT INTO daily_trade_reviews VALUES (?,?,?,?,?,?,?)",
                               (item["review_id"], *scope, item["source_hash"], version, _json(item)))
                # A later correction can restore earlier source contents.
                # Keep both immutable versions and point at the last observed
                # source; MAX(version) is not a current-state lookup.
                db.execute("""INSERT INTO daily_trade_review_current VALUES (?,?,?,?,?)
                    ON CONFLICT(book_id, accounting_day, schema_version)
                    DO UPDATE SET review_id=excluded.review_id, observed_at=excluded.observed_at""",
                    (*scope, item["review_id"], datetime.now(timezone.utc).isoformat()))
                saved.append(item)
            db.commit()
        except Exception:
            db.rollback()
            raise
    return saved


def _prepare_reviews(book_id, start, rows):
    partial_signatures = {_position_signature(r) for r in rows if r.get("status") == "closed_partial"}
    buckets = {}
    for row in rows:
        buckets.setdefault(_iso(row["exit_at"]).date().isoformat(), []).append(row)
    reviews = []
    for offset in range(REVIEW_DAYS):
        day = (start + timedelta(days=offset)).date().isoformat()
        reviews.append(_build_day(book_id, day, buckets.get(day, []), partial_signatures))
    return reviews


def _export(path, review):
    directory = path.parent / "daily_review_artifacts" / _hash(review["book_id"])[:20]
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{review['accounting_day']}-{review['review_id']}.json"
    text = json.dumps(review, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if destination.exists() and destination.read_text(encoding="utf-8") == text:
        return str(destination)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory,
                                     suffix=".tmp", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(text)
    try:
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return str(destination)


async def daily_review_for_book(client, book_id, *, settings=None, now=None):
    """Bounded observer-only review; no market-data, Mem0 or broker calls."""
    cfg = settings if settings is not None else get_settings()
    base = {"event": "daily_trade_review", "user_id": book_id,
            "accounting_timezone": "UTC", "execution_enabled": False,
            "strategy_promotion_eligible": False, "verified_return": None, "llm_calls": 0}
    if not getattr(cfg, "trezo_research_enabled", False):
        return {**base, "status": "disabled"}
    if not book_id or getattr(cfg, "trading_mode", "paper") != "paper" or client is None:
        return {**base, "status": "blocked", "reason": "configured_paper_book_required"}
    current = now if now is not None else datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        return {**base, "status": "blocked", "reason": "aware_timestamp_required"}
    end = current.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=REVIEW_DAYS)
    rows, receipt = await _read_rows(client, book_id, start, end)
    if rows is None:
        return {**base, **receipt, "status": "failed", "history_complete": False, "reviews": []}
    try:
        reviews = await asyncio.to_thread(_prepare_reviews, book_id, start, rows)
        configured = str(getattr(cfg, "trezo_research_db_path", "") or "")
        research_path = (Path(configured).expanduser() if configured else
                         Path(__file__).resolve().parents[2] / "local_state" / "research.sqlite3")
        path = research_path.parent / "daily_trade_reviews.sqlite3"
        saved = await asyncio.to_thread(_save_reviews, path, reviews)
    except Exception as exc:
        return {**base, **receipt, "status": "failed", "history_complete": True,
                "reason": "review_build_or_store_failed", "error_type": type(exc).__name__, "reviews": []}
    output = []
    for review in saved:
        artifact, export_error = None, None
        try:
            artifact = await asyncio.to_thread(_export, path, review)
        except Exception as exc:
            export_error = type(exc).__name__
        output.append({key: review[key] for key in
                       ("review_id", "accounting_day", "version", "source_hash", "recorded_row_count",
                        "recorded_pnl_usd", "sampled_peak_observation_count")} |
                      {"research_hint_count": len(review["research_hints"]),
                       "artifact_path": artifact, "artifact_export_error": export_error})
    return {**base, **receipt, **QUALIFICATIONS, "history_complete": True,
            "status": "incomplete" if any(r["artifact_export_error"] for r in output) else "completed",
            "window_start": start.isoformat(), "window_end_exclusive": end.isoformat(),
            "journal_path": str(path), "reviews": output}
