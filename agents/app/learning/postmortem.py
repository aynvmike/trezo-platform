"""Trade post-mortem analyzer — Phase 13/14 Mike-specific.

For each closed trade we already know entry_price, exit_price, side,
opened_at and closed_at. The analyzer fetches the candle series
covering that window plus a forward look (5 bars past close), then
computes:

- MFE (max favorable excursion): best unrealized P&L during the hold
- MAE (max adverse excursion): worst unrealized P&L during the hold
- Optimal exit: the bar that maximized realized P&L
- Gave-back %: how much of the MFE the trader gave back before closing
- Post-close move: how the price moved AFTER you closed

From those it diagnoses one of:
- 'optimal'           — exit within 5% of MFE (you nailed it)
- 'held_too_long'     — MFE peaked >2 bars before close, gave back >50%
- 'exited_too_early'  — price kept moving in your favor >5% after close
- 'stop_too_tight'    — MAE hit your stop before MFE could develop
- 'late_to_stop'      — stop blew through; you held past the obvious exit
- 'no_signal'         — couldn't decide (sparse data, etc.)

Mike's stated weak spot is holding too long. The 'held_too_long' diag
specifically tracks the gap between peak MFE and close, in bars and %.

Designed to run idempotently — re-running just rewrites the postmortem
column. Skips rows already analyzed unless `force=True`.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import structlog

from app.config import get_settings
from app.data.candles import fetch_candles_for, fetch_crypto_ohlc, COIN_MAP
from app.patterns.candle import Candle

log = structlog.get_logger("trezo.learning.postmortem")


# How far past close to look for "exited too early" signal. 5 bars is
# enough for daily data to show whether the trend continued or reversed.
LOOK_FORWARD_BARS = 5


@dataclass
class PostMortem:
    mfe_price: Optional[float]              # best price during hold
    mfe_at: Optional[str]                   # ISO timestamp of that bar
    mfe_pnl_usd: Optional[float]            # MFE realized at that bar
    mae_price: Optional[float]              # worst price during hold
    mae_at: Optional[str]
    mae_pnl_usd: Optional[float]
    optimal_exit_price: Optional[float]     # MFE = optimal for closed trade
    realized_pnl_usd: Optional[float]       # what they actually got
    capture_pct: Optional[float]            # realized / mfe
    gave_back_pct: Optional[float]          # (mfe - realized) / mfe
    post_close_5bar_pct: Optional[float]    # price move in the 5 bars after close
    bars_held: Optional[int]
    bars_to_mfe: Optional[int]              # how many bars in MFE peaked
    diagnosis: str                          # one of the tags above
    narrative: str                          # plain-English explanation


def _supabase():
    s = get_settings()
    if not s.supabase_url or not s.supabase_service_role_key:
        return None
    try:
        from supabase import create_client
        return create_client(s.supabase_url, s.supabase_service_role_key)
    except Exception:  # noqa: BLE001
        return None


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        return None


def _trade_pnl(side: str, entry: float, price: float, qty: float) -> float:
    if side == "short":
        return qty * (entry - price)
    return qty * (price - entry)


def _diagnose(
    side: str,
    entry: float,
    exit_price: float,
    qty: float,
    in_window: list[Candle],
    post_window: list[Candle],
) -> PostMortem:
    """Run the math on a single trade's candle window."""
    if not in_window:
        return PostMortem(
            mfe_price=None, mfe_at=None, mfe_pnl_usd=None,
            mae_price=None, mae_at=None, mae_pnl_usd=None,
            optimal_exit_price=None, realized_pnl_usd=None,
            capture_pct=None, gave_back_pct=None,
            post_close_5bar_pct=None,
            bars_held=0, bars_to_mfe=None,
            diagnosis="no_signal",
            narrative="Not enough historical data to replay this trade.",
        )

    realized = _trade_pnl(side, entry, exit_price, qty)

    # Per-bar favorable / adverse excursion. For a long, favorable =
    # high; for a short, favorable = low.
    best_pnl = float("-inf")
    best_bar = 0
    worst_pnl = float("inf")
    worst_bar = 0
    for i, c in enumerate(in_window):
        fav_price = c.high if side == "long" else c.low
        adv_price = c.low if side == "long" else c.high
        fp = _trade_pnl(side, entry, fav_price, qty)
        ap = _trade_pnl(side, entry, adv_price, qty)
        if fp > best_pnl:
            best_pnl = fp
            best_bar = i
        if ap < worst_pnl:
            worst_pnl = ap
            worst_bar = i

    bars_held = len(in_window)
    bars_to_mfe = best_bar
    mfe_price = (in_window[best_bar].high
                 if side == "long" else in_window[best_bar].low)
    mfe_at = in_window[best_bar].timestamp.isoformat()
    mae_price = (in_window[worst_bar].low
                 if side == "long" else in_window[worst_bar].high)
    mae_at = in_window[worst_bar].timestamp.isoformat()

    # How much of the MFE you actually captured. Negative when the
    # close was worse than the MAE (e.g. stopped through).
    capture_pct: Optional[float] = None
    gave_back_pct: Optional[float] = None
    if best_pnl > 0:
        capture_pct = round(realized / best_pnl, 4)
        gave_back_pct = round(max(0.0, (best_pnl - realized) / best_pnl), 4)

    # Post-close move: did the price keep going in your favor?
    post_pct: Optional[float] = None
    if post_window:
        ref_after = (max(c.high for c in post_window) if side == "long"
                     else min(c.low for c in post_window))
        if exit_price > 0:
            move = (ref_after - exit_price) / exit_price
            # Sign so positive = you missed out.
            if side == "short":
                move = -move
            post_pct = round(move, 4)

    # Diagnosis rules — cheap and explainable on purpose.
    diagnosis = "no_signal"
    narrative = ""

    # Optimal: within 5% of MFE captured.
    if capture_pct is not None and capture_pct >= 0.95:
        diagnosis = "optimal"
        narrative = (
            f"Exit captured {capture_pct*100:.0f}% of the best move. "
            "Hard to do better."
        )
    # Held too long: MFE peaked early and you gave back >50%.
    elif (gave_back_pct is not None and gave_back_pct >= 0.50
          and bars_to_mfe is not None
          and (bars_held - bars_to_mfe) >= 2):
        diagnosis = "held_too_long"
        narrative = (
            f"Best price was hit {bars_held - bars_to_mfe} bars before "
            f"you closed, then gave back {gave_back_pct*100:.0f}% of the "
            "winnings. Consider trailing stops or a partial profit-take "
            "rule when the move exceeds your target."
        )
    # Exited too early: price kept running.
    elif post_pct is not None and post_pct >= 0.05:
        diagnosis = "exited_too_early"
        narrative = (
            f"Price continued in your favor by {post_pct*100:.0f}% over the "
            f"{len(post_window)} bars after you closed. The setup wasn't "
            "exhausted; consider a wider trail or a target above your exit."
        )
    # Stop too tight: worst point hit the stop before best could develop.
    elif (best_pnl <= 0 and worst_pnl < 0
          and bars_to_mfe is not None
          and worst_bar < bars_to_mfe):
        diagnosis = "stop_too_tight"
        narrative = (
            "The adverse move that closed you out arrived before any "
            "favorable move could develop. A slightly wider stop "
            "(measured against ATR) might have given the thesis room "
            "to breathe."
        )
    # Late to stop: you took a beating well past the obvious exit point.
    elif worst_pnl < 0 and realized < worst_pnl * 0.85:
        diagnosis = "late_to_stop"
        narrative = (
            f"The worst point ({mae_at}) printed earlier than your close, "
            "and you closed even lower. A pre-set stop based on the "
            "strategy's typical risk would have ended the trade sooner."
        )
    else:
        diagnosis = "no_signal"
        narrative = (
            "The replay didn't show a clear lesson — the move was small "
            "or the data window was too thin."
        )

    return PostMortem(
        mfe_price=round(mfe_price, 4) if mfe_price else None,
        mfe_at=mfe_at,
        mfe_pnl_usd=round(best_pnl, 2) if best_pnl != float("-inf") else None,
        mae_price=round(mae_price, 4) if mae_price else None,
        mae_at=mae_at,
        mae_pnl_usd=round(worst_pnl, 2) if worst_pnl != float("inf") else None,
        optimal_exit_price=round(mfe_price, 4) if mfe_price else None,
        realized_pnl_usd=round(realized, 2),
        capture_pct=capture_pct,
        gave_back_pct=gave_back_pct,
        post_close_5bar_pct=post_pct,
        bars_held=bars_held,
        bars_to_mfe=bars_to_mfe,
        diagnosis=diagnosis,
        narrative=narrative,
    )


async def _fetch_window(
    ticker: str, opened: datetime, closed: datetime,
) -> tuple[list[Candle], list[Candle]]:
    """Return (in_window, post_window) candles. Uses daily bars to keep
    the API budget reasonable; intraday refinement is a future step."""
    asset_type = "crypto" if ticker.upper() in COIN_MAP else "stock"
    candles: list[Candle] = []
    try:
        if asset_type == "crypto":
            candles = await fetch_crypto_ohlc(ticker, days=180)
        else:
            candles = await fetch_candles_for(ticker, "stock")
    except Exception as e:  # noqa: BLE001
        log.warning("postmortem.fetch_failed",
                    ticker=ticker, error=str(e)[:200])
        return [], []

    if not candles:
        return [], []

    in_window: list[Candle] = []
    post_window: list[Candle] = []
    for c in candles:
        ts = c.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts <= opened:
            continue
        if ts <= closed:
            in_window.append(c)
        else:
            post_window.append(c)
            if len(post_window) >= LOOK_FORWARD_BARS:
                break
    return in_window, post_window


async def run_postmortem_for_user(
    user_id: str, force: bool = False, max_rows: int = 200,
) -> dict[str, Any]:
    """Analyze the user's trade_outcomes rows. Skips rows already
    analyzed unless force=True. Returns a summary."""
    client = _supabase()
    if not client:
        return {"ok": False, "error": "Supabase not configured"}

    def _sync_get():
        q = (client.table("trade_outcomes")
             .select("id, ticker, side, entry_price, exit_price, "
                     "quantity, opened_at, closed_at, postmortem_ran_at")
             .eq("user_id", user_id)
             .order("closed_at", desc=True)
             .limit(max_rows))
        return q.execute()

    try:
        res = await asyncio.to_thread(_sync_get)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:200]}

    rows = res.data or []
    analyzed = 0
    skipped = 0
    by_diag: dict[str, int] = {}

    for row in rows:
        if row.get("postmortem_ran_at") and not force:
            skipped += 1
            continue
        try:
            ticker = (row.get("ticker") or "").upper()
            side = (row.get("side") or "long").lower()
            entry = float(row.get("entry_price") or 0)
            exit_price = float(row.get("exit_price") or 0)
            qty = float(row.get("quantity") or 1)
            opened = _parse_iso(row.get("opened_at"))
            closed = _parse_iso(row.get("closed_at"))

            if not ticker or not opened or not closed or entry <= 0 or exit_price <= 0:
                continue

            in_window, post_window = await _fetch_window(ticker, opened, closed)
            pm = _diagnose(side, entry, exit_price, qty, in_window, post_window)

            def _sync_update(rid=row["id"], pm=pm):
                return (
                    client.table("trade_outcomes")
                    .update({
                        "postmortem": asdict(pm),
                        "postmortem_diagnosis": pm.diagnosis,
                        "postmortem_ran_at": datetime.now(timezone.utc).isoformat(),
                    })
                    .eq("id", rid)
                    .execute()
                )

            await asyncio.to_thread(_sync_update)
            analyzed += 1
            by_diag[pm.diagnosis] = by_diag.get(pm.diagnosis, 0) + 1
        except Exception as e:  # noqa: BLE001
            log.warning("postmortem.row_failed",
                        row_id=row.get("id"), error=str(e)[:200])
            continue

    return {
        "ok": True,
        "scanned": len(rows),
        "analyzed": analyzed,
        "skipped": skipped,
        "by_diagnosis": by_diag,
    }
