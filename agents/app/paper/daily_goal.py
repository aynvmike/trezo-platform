"""Daily income goal -- the agents' paycheck target (Mike 2026-07-13).

Mike: "I would like for them to try to make 50 bucks a day as a goal and
then it can move to standard averages of working employees" -- ~$58k/yr
to live, ~$75k to live better, ~$125k comfortable; his six-figure marker
is $293/day. The ladder below encodes those rungs. The ACTIVE rung is
picked by account size so the goal is always one the account can chase
SAFELY: a $5k account grinds the $50 rung (~1%/day); the $293 rung waits
until ~$20k of equity where it is a ~1.5% day -- inside Mike's stated
1-3% band for a $15-25k account.

BEHAVIORAL CONTRACT (do not weaken): the goal NEVER loosens a gate.
It only ever
  (a) makes the agents PICKIER once the day's goal is banked
      (+5 TCS on new entries -- protect the paycheck), and
  (b) nudges the profit ladder to bank a touch EARLIER in the
      afternoon when the day is still behind.
No revenge trading, no pressure sizing, no chasing.

Env: TREZO_DAILY_GOAL forces a $ amount; TREZO_GOAL_MAX_PCT is the
rung-selection safety ceiling as a fraction of equity (default 0.015).
"""

from __future__ import annotations

import os
import time
from datetime import date

# (daily $, label) -- Mike's ladder of working-life pay, in trading days.
GOAL_RUNGS: list[tuple[float, str]] = [
    (50.0, "grind"),              # first paycheck
    (110.0, "steady"),            # ~$28k/yr pace
    (225.0, "living wage"),       # ~$58k/yr -- "lives on its own"
    (293.0, "six-figure pace"),   # Mike's marker
    (480.0, "comfortable"),       # ~$125k/yr
]

_DY_CACHE: dict[str, tuple[float, float]] = {}   # uid -> (ts, today $) 60s
_HIT_MARK: dict[str, str] = {}                   # uid -> date already logged


def _resolve_uid(user_id) -> str:
    return str(user_id or os.getenv("TREZO_PRIMARY_USER_ID", "") or "")


def daily_goal_for(equity: float) -> tuple[float, str]:
    """Highest rung the account can chase safely: rung <= equity * ceiling
    (default 1.5%/day), with the $50 grind rung as the floor for any
    account big enough to trade. TREZO_DAILY_GOAL forces a number."""
    forced = os.getenv("TREZO_DAILY_GOAL", "")
    if forced:
        try:
            return (max(1.0, float(forced)), "custom")
        except Exception:  # noqa: BLE001
            pass
    try:
        ceiling = float(os.getenv("TREZO_GOAL_MAX_PCT", "0.015"))
    except Exception:  # noqa: BLE001
        ceiling = 0.015
    cap = max(50.0, float(equity or 0.0) * ceiling)
    amount, label = GOAL_RUNGS[0]
    for amt, lbl in GOAL_RUNGS:
        if amt <= cap:
            amount, label = amt, lbl
    return (amount, label)


async def today_realized(user_id) -> float:
    """Today's realized P&L from row truth. Prefers the kill-switch's 30s
    row-sum cache (refreshed on every signal while the desk is live);
    falls back to one direct query cached 60s. Fail-open 0.0."""
    uid = _resolve_uid(user_id)
    if not uid:
        return 0.0
    try:
        from app.paper.killswitch import _ROWSUM_CACHE
        hit = _ROWSUM_CACHE.get(uid)
        if hit and (time.time() - hit[0]) < 30.0:
            return float(hit[2])
    except Exception:  # noqa: BLE001
        pass
    hit2 = _DY_CACHE.get(uid)
    if hit2 and (time.time() - hit2[0]) < 60.0:
        return float(hit2[1])
    try:
        import asyncio
        from app.runtime.settings import _supabase as _sb
        client = _sb()
        if client is None:
            return 0.0
        today_s = date.today().isoformat()

        def _rows():
            return (client.table("paper_positions")
                    .select("realized_pnl_usd")
                    .eq("user_id", uid)
                    .gte("exit_at", today_s)
                    .like("status", "closed%")
                    .limit(500).execute())
        rr = (await asyncio.to_thread(_rows)).data or []
        dy = round(sum(float(x.get("realized_pnl_usd") or 0) for x in rr), 2)
        _DY_CACHE[uid] = (time.time(), dy)
        return dy
    except Exception:  # noqa: BLE001
        return 0.0


async def goal_state(user_id) -> dict:
    """One snapshot: goal, label, equity, realized, hit, pct (0-100),
    week_goal (goal x 5), week_realized (when warm). Never raises."""
    uid = _resolve_uid(user_id)
    eq = 0.0
    try:
        from app.paper.allocation import effective_equity
        eq = await effective_equity(uid)
    except Exception:  # noqa: BLE001
        eq = 0.0
    goal, label = daily_goal_for(eq)
    dy = await today_realized(uid)
    wk = None
    try:
        from app.paper.killswitch import _ROWSUM_CACHE
        hit = _ROWSUM_CACHE.get(uid)
        if hit and (time.time() - hit[0]) < 30.0:
            wk = float(hit[1])
    except Exception:  # noqa: BLE001
        pass
    return {
        "goal": goal, "label": label,
        "equity": round(float(eq or 0.0), 2),
        "realized": dy, "hit": bool(goal and dy >= goal),
        "pct": (round(min(100.0, max(0.0, (dy / goal) * 100.0)), 1)
                if goal else 0.0),
        "week_goal": round(goal * 5, 2),
        "week_realized": wk,
    }


def mark_goal_hit_once(user_id) -> bool:
    """True only the FIRST time today (one clean activity line, no spam)."""
    uid, today_s = _resolve_uid(user_id), date.today().isoformat()
    if _HIT_MARK.get(uid) == today_s:
        return False
    _HIT_MARK[uid] = today_s
    return True
