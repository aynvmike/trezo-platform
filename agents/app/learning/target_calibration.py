"""Outcome-driven target calibration (Mike 2026-07-08).

"If the ten percent goal has been too high lately, adjust to a number
that has been reached on average and test the same strategy there."

Every closed position row records its PEAK (max favorable excursion).
That peak is the honest answer to "what did this strategy's trades
actually achieve?" -- so the formula layer caps each new trade's target
at the recent MEDIAN achieved move for that (strategy, asset_type),
instead of wishing for a number the tape hasn't been paying.

Fail-open by design: fewer than MIN_SAMPLES closed trades, any query
error, or a zero median -> None, and the strategy trades on its normal
geometry. Cached in-process for an hour per lane.

Tunables (agents/.env):
  TREZO_LEARNED_TARGET_ENABLED       1 (default on)
  TREZO_LEARNED_TARGET_MIN_SAMPLES   5
  TREZO_LEARNED_TARGET_MULT          1.0   (cap = mult x median peak)
  TREZO_LEARNED_TARGET_LOOKBACK      20    (most recent closed trades)
"""

from __future__ import annotations

import os
import time as _time
from typing import Optional

_CACHE: dict[str, tuple[float, Optional[float], int]] = {}
_TTL = 3600.0


def enabled() -> bool:
    return os.getenv("TREZO_LEARNED_TARGET_ENABLED", "1") != "0"


async def achieved_move_pct(strategy: str, asset_type: str,
                            user_id: Optional[str] = None
                            ) -> tuple[Optional[float], int]:
    """Median peak gain (fraction, e.g. 0.021 = 2.1%) across the lane's
    recent closed trades, and the sample count. (None, n) when there is
    not enough history -- callers must fail open."""
    if not enabled():
        return None, 0
    lane = f"{(strategy or 'unknown').lower()}|{(asset_type or 'stock').lower()}"
    hit = _CACHE.get(lane)
    if hit and (_time.time() - hit[0]) < _TTL:
        return hit[1], hit[2]
    med: Optional[float] = None
    n = 0
    try:
        from app.runtime.settings import _supabase
        client = _supabase()
        if client is None:
            return None, 0
        lookback = int(float(os.getenv("TREZO_LEARNED_TARGET_LOOKBACK", "20")))
        min_n = int(float(os.getenv("TREZO_LEARNED_TARGET_MIN_SAMPLES", "5")))

        def _q():
            q = (client.table("paper_positions")
                 .select("side, entry_price, peak_price")
                 .eq("strategy", strategy)
                 .like("status", "closed%")
                 .order("exit_at", desc=True)
                 .limit(lookback))
            if user_id:
                q = q.eq("user_id", user_id)
            return q.execute()
        import asyncio
        rows = (await asyncio.to_thread(_q)).data or []
        moves: list[float] = []
        for r in rows:
            try:
                e = float(r.get("entry_price") or 0)
                p = float(r.get("peak_price") or 0)
                if e <= 0 or p <= 0:
                    continue
                side = str(r.get("side") or "long")
                mv = (p - e) / e if side == "long" else (e - p) / e
                if mv > 0:
                    moves.append(mv)
            except (TypeError, ValueError):
                continue
        n = len(moves)
        if n >= min_n:
            moves.sort()
            mid = n // 2
            med = (moves[mid] if n % 2 == 1
                   else (moves[mid - 1] + moves[mid]) / 2.0)
            if med <= 0:
                med = None
    except Exception:  # noqa: BLE001
        med, n = None, 0
    _CACHE[lane] = (_time.time(), med, n)
    return med, n
