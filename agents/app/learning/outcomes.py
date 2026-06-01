"""Outcome recorder + stats helpers for the Phase 13/14 learning loop.

The recorder writes one `trade_outcomes` row each time a paper or live
position closes. The stats helpers read those rows back and roll them
into per-strategy / per-cycle / per-regime breakdowns.

Design contract:
- `record_paper_close(...)` is called by `paper.engine.close_position`
  after the position update succeeds. Failures here NEVER block the
  close — the trade is real and committed; the record is bookkeeping.
- The recorder reads the closed paper_positions row's
  `source_payload` jsonb to pull the originating signal's TCS, cycle
  position, regime, and pattern breakdown. This decouples the
  learning ledger from the source schema.
- `get_strategy_stats(user_id, lookback_days)` returns a dict ready
  for both the Learning Insights panel and any future auto-tuner.
"""

from __future__ import annotations

import asyncio
import statistics
from typing import Any, Optional

import structlog

from app.config import get_settings

log = structlog.get_logger("trezo.learning")


def _supabase():
    s = get_settings()
    if not s.supabase_url or not s.supabase_service_role_key:
        return None
    try:
        from supabase import create_client
        return create_client(s.supabase_url, s.supabase_service_role_key)
    except Exception:  # noqa: BLE001
        return None


async def record_paper_close(
    *,
    user_id: str,
    position_id: str,
    ticker: str,
    asset_type: str,
    side: str,
    strategy: Optional[str],
    direction: Optional[str],
    entry_price: float,
    exit_price: float,
    quantity: float,
    realized_pnl_usd: float,
    exit_reason: str,
    status: str,
    opened_at: Optional[str],
    closed_at: Optional[str],
    source_payload: Optional[dict[str, Any]] = None,
) -> None:
    """Insert one `trade_outcomes` row. Best-effort; never raises."""
    client = _supabase()
    if not client:
        return

    payload = source_payload or {}
    cycle = payload.get("cycle") or {}
    breakdown = payload.get("breakdown") or payload.get("pattern_weights")
    scope = payload.get("scope") or {}

    # Compute hold time when both timestamps are populated.
    hold_minutes: Optional[int] = None
    if opened_at and closed_at:
        try:
            from datetime import datetime
            a = datetime.fromisoformat(opened_at.replace("Z", "+00:00"))
            b = datetime.fromisoformat(closed_at.replace("Z", "+00:00"))
            hold_minutes = max(0, int((b - a).total_seconds() // 60))
        except Exception:  # noqa: BLE001
            hold_minutes = None

    row = {
        "user_id": user_id,
        "position_id": position_id,
        "source_table": "paper_positions",
        "ticker": ticker,
        "asset_type": asset_type,
        "side": side,
        "strategy": strategy,
        "direction": direction or payload.get("direction"),
        "tcs_at_entry": payload.get("tcs"),
        "iv_environment_at_entry": cycle.get("iv_environment"),
        "regime_at_entry": scope.get("regime") or payload.get("regime"),
        "scope_paused_at_entry": scope.get("paused_strategies"),
        "pattern_breakdown": breakdown,
        "entry_payload": payload,
        "exit_reason": exit_reason,
        "status": status,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "quantity": quantity,
        "realized_pnl_usd": realized_pnl_usd,
        "hold_minutes": hold_minutes,
        "opened_at": opened_at,
        "closed_at": closed_at,
    }

    def _sync():
        return client.table("trade_outcomes").insert(row).execute()

    try:
        await asyncio.to_thread(_sync)
    except Exception as e:  # noqa: BLE001
        log.warning("learning.record_failed",
                    position_id=position_id, error=str(e)[:200])


# ----------------------------------------------------------------------
# Stats helpers
# ----------------------------------------------------------------------

def _median(xs: list[float]) -> Optional[float]:
    if not xs:
        return None
    return float(statistics.median(xs))


def _bucket(rows: list[dict], key: str) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in rows:
        k = (r.get(key) or "_unknown")
        out.setdefault(str(k), []).append(r)
    return out


def _summarise(rows: list[dict]) -> dict[str, Any]:
    """Per-bucket stats. Wins are realized_pnl_usd > 0; scratches
    (pnl == 0) sit between - they don't count for or against the win
    rate, matching the dashboard's existing convention."""
    wins = [r for r in rows if (r.get("realized_pnl_usd") or 0) > 0]
    losses = [r for r in rows if (r.get("realized_pnl_usd") or 0) < 0]
    decided = len(wins) + len(losses)
    win_rate = (len(wins) / decided) if decided > 0 else None
    return {
        "n": len(rows),
        "wins": len(wins),
        "losses": len(losses),
        "scratches": len(rows) - decided,
        "win_rate": round(win_rate, 4) if win_rate is not None else None,
        "total_pnl_usd": round(
            sum(float(r.get("realized_pnl_usd") or 0) for r in rows), 2),
        "avg_win_usd": round(
            sum(float(r.get("realized_pnl_usd") or 0) for r in wins) / len(wins), 2)
            if wins else None,
        "avg_loss_usd": round(
            sum(float(r.get("realized_pnl_usd") or 0) for r in losses) / len(losses), 2)
            if losses else None,
        "median_tcs_winners": _median(
            [r["tcs_at_entry"] for r in wins if r.get("tcs_at_entry") is not None]),
        "median_tcs_losers": _median(
            [r["tcs_at_entry"] for r in losses if r.get("tcs_at_entry") is not None]),
        "median_hold_minutes": _median(
            [r["hold_minutes"] for r in rows if r.get("hold_minutes") is not None]),
    }


async def get_strategy_stats(
    user_id: str,
    lookback_days: int = 30,
) -> dict[str, Any]:
    """Return per-strategy + per-cycle + per-regime breakdowns for the
    user's last `lookback_days` of closed trades."""
    client = _supabase()
    if not client:
        return {"configured": False, "by_strategy": {}, "by_cycle": {},
                "by_regime": {}, "n": 0}

    def _sync():
        from datetime import datetime, timedelta, timezone
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=lookback_days)
        ).isoformat()
        return (
            client.table("trade_outcomes")
            .select("strategy, tcs_at_entry, realized_pnl_usd, "
                    "iv_environment_at_entry, regime_at_entry, hold_minutes, "
                    "ticker, closed_at")
            .eq("user_id", user_id)
            .gte("closed_at", cutoff)
            .execute()
        )

    try:
        res = await asyncio.to_thread(_sync)
        rows = res.data or []
    except Exception as e:  # noqa: BLE001
        log.warning("learning.stats_failed", error=str(e)[:200])
        return {"configured": True, "error": str(e)[:200],
                "by_strategy": {}, "by_cycle": {}, "by_regime": {}, "n": 0}

    by_strategy = {k: _summarise(v) for k, v in _bucket(rows, "strategy").items()}
    by_cycle = {k: _summarise(v)
                for k, v in _bucket(rows, "iv_environment_at_entry").items()}
    by_regime = {k: _summarise(v)
                 for k, v in _bucket(rows, "regime_at_entry").items()}

    return {
        "configured": True,
        "lookback_days": lookback_days,
        "n": len(rows),
        "by_strategy": by_strategy,
        "by_cycle": by_cycle,
        "by_regime": by_regime,
    }


def suggest_tuning(strategy_stats: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn per-strategy stats into plain-English suggestions. Returns
    a list of dicts that the UI can render with a "Apply" button.

    The rules are intentionally simple — a tiny knob-tuner, not an
    optimizer. Auto-apply is OFF; suggestions live in a sidebar.
    """
    out: list[dict[str, Any]] = []
    for strat, s in (strategy_stats.get("by_strategy") or {}).items():
        if s["n"] < 6 or s["wins"] == 0 or s["losses"] == 0:
            continue
        wt = s.get("median_tcs_winners")
        lt = s.get("median_tcs_losers")
        if wt is None or lt is None:
            continue
        gap = wt - lt
        # Winners need to be noticeably higher-TCS than losers to be a
        # real signal. >= 60 TCS is the cutoff we use as a sanity gate.
        if gap >= 60:
            target = int(round((wt - 50) / 25) * 25)
            out.append({
                "strategy": strat,
                "kind": "raise_tcs_floor",
                "current_median_winners": int(wt),
                "current_median_losers": int(lt),
                "suggested_tcs_floor": target,
                "note": (
                    f"{strat.upper()} winners had median TCS {int(wt)} vs "
                    f"losers at {int(lt)} ({gap:.0f} point gap). "
                    f"Consider raising the TCS floor toward {target}."
                ),
            })
        elif (s.get("win_rate") or 0) < 0.35 and s["n"] >= 10:
            out.append({
                "strategy": strat,
                "kind": "pause_strategy",
                "win_rate": s["win_rate"],
                "note": (
                    f"{strat.upper()} is at {s['win_rate']*100:.0f}% win rate "
                    f"over {s['n']} trades. Consider pausing in Bot Tuning "
                    "while you investigate."
                ),
            })
    return out
