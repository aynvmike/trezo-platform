"""Bind bounded historical research to discovery, with no Discord/LLM dependency.

Only public market-data snapshots are shared between books. Research journals,
jobs, candidate lineage and result artifacts remain scoped to the owning book.
This pilot neither changes a strategy selector nor creates financial transfers.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import tempfile

from app.config import get_settings
from app.research.capital import CapitalUnavailable, read_capital_snapshot

_DATA_CACHE: dict[tuple[str, str, str], list] = {}


async def _fetch_daily(symbol: str, asset_type: str) -> list:
    from app.data.candles import fetch_crypto_ohlc, fetch_stock_candles
    if asset_type == "crypto":
        return await fetch_crypto_ohlc(symbol, days=365)
    return await fetch_stock_candles(symbol, period="2y", interval="1d")


def _finite_number(value, label: str, *, positive: bool = False) -> float:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{label} must be explicitly configured")
    number = float(value)
    if not math.isfinite(number) or number < 0 or (positive and number == 0):
        raise ValueError(f"invalid {label}")
    return number


def _export(db_path: Path, book_id: str, result: dict) -> str:
    """Atomic replace after the authoritative SQLite transaction commits."""
    book_key = hashlib.sha256(book_id.encode()).hexdigest()[:20]
    job_key = hashlib.sha256(str(result["job_id"]).encode()).hexdigest()
    directory = db_path.parent / "research_artifacts" / book_key
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{job_key}.json"
    # A result is explicitly historical research, never a live return statement.
    evidence = {key: value for key, value in result.items() if key != "cached"}
    serialized = json.dumps(evidence, indent=2, sort_keys=True, allow_nan=False)
    if destination.exists() and destination.read_text(encoding="utf-8") == serialized + "\n":
        return str(destination)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory,
                                     suffix=".tmp", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(serialized + "\n")
    try:
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return str(destination)


async def research_for_book(book_id: str, *, settings=None,
                            now: datetime | None = None) -> dict:
    """One daily equity-based cycle or at most two fixed scenarios per book.

    Missing configuration/data/storage produces a visible blocked/failed result.
    The full journal is local to one engine; use centralized storage before
    deploying multiple engine hosts for the same research books.
    """
    cfg = settings if settings is not None else get_settings()
    base = {"event": "internal_research", "user_id": book_id,
            "execution_enabled": False, "forward_evidence_required": True,
            "method": "restricted_rule_composition", "llm_calls": 0}
    if not getattr(cfg, "trezo_research_enabled", False):
        return {**base, "status": "disabled"}
    if not book_id or getattr(cfg, "trading_mode", "paper") != "paper":
        return {**base, "status": "blocked", "reason": "paper_book_required"}
    try:
        symbol = str(getattr(cfg, "trezo_research_symbol", "SPY")).strip().upper()
        asset_type = str(getattr(cfg, "trezo_research_asset_type", "stock"))
        if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", symbol):
            raise ValueError("invalid research symbol")
        if asset_type not in {"stock", "crypto"}:
            raise ValueError("unsupported research asset type")
        fee = _finite_number(getattr(cfg, "trezo_research_commission_bps", None), "commission")
        slip = _finite_number(getattr(cfg, "trezo_research_slippage_bps", None), "slippage")
        if fee > 200 or slip > 200:
            raise ValueError("research cost assumption exceeds pilot bounds")
        capital_mode = str(getattr(cfg, "trezo_research_capital_mode", "broker_equity"))
        if capital_mode not in {"broker_equity", "fixed_scenario"}:
            raise ValueError("unsupported research capital mode")
        capitals = []
        if capital_mode == "fixed_scenario":
            capitals = sorted(set(_finite_number(v.strip(), "capital", positive=True)
                                  for v in str(getattr(cfg, "trezo_research_capitals", "1000,5000")).split(",")))
            if not 1 <= len(capitals) <= 2 or any(not 1 <= c <= 1_000_000 for c in capitals):
                raise ValueError("pilot permits one or two capital cases")
    except (TypeError, ValueError):
        return {**base, "status": "blocked", "reason": "invalid_or_missing_research_configuration"}

    current = now if now is not None else datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        return {**base, "status": "blocked", "reason": "aware_timestamp_required"}
    current = current.astimezone(timezone.utc)
    day = current.date().isoformat()
    capital_snapshot = None
    if capital_mode == "broker_equity":
        try:
            capital_snapshot = await read_capital_snapshot(book_id)
            capitals = [capital_snapshot["equity_usd"]]
        except CapitalUnavailable as exc:
            return {**base, "status": "blocked", "reason": str(exc),
                    "capital_basis": capital_mode,
                    **({"capital_read_diagnostic": exc.diagnostic} if exc.diagnostic else {})}
        except Exception as exc:
            return {**base, "status": "failed", "reason": "research_equity_read_failed",
                    "capital_basis": capital_mode, "error_type": type(exc).__name__}
    cache_key = (symbol, asset_type, day)
    try:
        if cache_key not in _DATA_CACHE:
            fetched = await asyncio.wait_for(_fetch_daily(symbol, asset_type), timeout=45)
            # Conservative daily-bar closure: no unfinished daily candle enters research.
            candles = [c for c in fetched if c.timestamp + timedelta(days=1) <= current]
            if len(candles) < 180 or current - candles[-1].timestamp > timedelta(days=10):
                return {**base, "status": "blocked", "reason": "insufficient_or_stale_completed_daily_bars"}
            from app.research.core import normalize_candles
            normalize_candles(candles[-1200:])  # never cache malformed data for the whole day
            _DATA_CACHE.clear()  # bounded cache; contains public prices, never account state
            _DATA_CACHE[cache_key] = candles[-1200:]
        candles = _DATA_CACHE[cache_key]
    except Exception as exc:  # data adapter failure must not stop sibling accounts
        return {**base, "status": "failed", "reason": "market_data_unavailable",
                "error_type": type(exc).__name__}

    configured_path = str(getattr(cfg, "trezo_research_db_path", "") or "")
    db_path = (Path(configured_path).expanduser() if configured_path else
               Path(__file__).resolve().parents[2] / "local_state" / "research.sqlite3")
    # parents[2] is app's parent (agents); independent of service working directory.
    from app.research.cycle import run_cycle
    cases = []
    for capital in capitals:
        try:
            result = await asyncio.to_thread(
                run_cycle, str(db_path), book_id=book_id, symbol=symbol,
                candles=candles, starting_capital=capital,
                commission_bps=fee, slippage_bps=slip,
                capital_basis=capital_mode, capital_snapshot=capital_snapshot,
                cycle_key=f"daily-v1:{asset_type}:{day}")
            artifact = None
            artifact_error = None
            if result.get("status") == "completed":
                try:
                    artifact = await asyncio.to_thread(_export, db_path, book_id, result)
                except Exception as exc:
                    artifact_error = type(exc).__name__
            # Reused daily evidence must describe its FROZEN capital, even
            # when the fresh account read has changed during this day.
            frozen_capital = result.get("assumptions", {}).get("starting_capital")
            cases.append({"starting_capital": frozen_capital, "status": result.get("status"),
                          "capital_basis": capital_mode,
                          "capital_snapshot": result.get("capital_snapshot"),
                          "job_id": result.get("job_id"), "dataset_hash": result.get("dataset_hash"),
                          "trial_count": len(result.get("trials", [])),
                          "artifact_path": artifact, "artifact_export_error": artifact_error,
                          "reason": result.get("reason")})
        except Exception as exc:
            cases.append({"starting_capital": capital, "status": "failed",
                          "reason": "research_cycle_failed", "error_type": type(exc).__name__})
    return {**base, "status": "completed" if all(c["status"] == "completed" for c in cases) else "incomplete",
            "symbol": symbol, "asset_type": asset_type, "capital_basis": capital_mode,
            "latest_capital_snapshot": capital_snapshot, "cases": cases}
