"""Kill-switches — the daily and weekly safety halts.

Phase 8c, from TREZO_NOVA_BOT_TRADE_RULES.md Section 1. When any switch
trips, the Risk Manager vetoes every new signal:

  - Daily:   today's realized loss reaches 3% of the day-start equity
  - Weekly:  this week's realized loss reaches 6% of the week-start equity
  - Streak:  3 losing trades in a row
  - Rejects: 3+ broker order rejects in one session

Daily and streak halts clear at the next daily roll; the weekly halt
clears at the next weekly roll (Monday). The slippage and market-data
quality halts from the document are deferred until real (non-modeled)
fills exist to measure.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

DAILY_DRAWDOWN_PCT = 0.03
WEEKLY_DRAWDOWN_PCT = 0.06
MAX_CONSECUTIVE_LOSSES = 3
MAX_BROKER_REJECTS = 3
MAX_SLIPPAGE_BREACHES = 3   # fills slipping worse than the limit / session

_ROWSUM_CACHE: dict[str, tuple] = {}   # user -> (ts, wk, dy, streak) 30s TTL


class _RowsumCached(Exception):
    """Internal flow control: row-truth served from cache."""


# --- Broker-reject counter on a ROLLING WINDOW (in-process) -----------
# Mike 2026-07-27: this halt was "session"-scoped with no expiry, so
# three rejects on Friday afternoon silenced the WHOLE weekend -- 293
# blocked signals in the 24/7 market that is supposed to earn dailies.
# A reject storm should pause trading briefly, not forever. Rejects now
# AGE OUT after TREZO_BROKER_REJECT_WINDOW_MIN (default 60), so the halt
# heals itself the same way the bad-symbol rest list expires. Same
# philosophy as everywhere else: conditions, never permanent bans.
import os as _os_ks
import time as _time_ks

_broker_reject_ts: list[float] = []


def _reject_window_s() -> float:
    try:
        return max(60.0, float(
            _os_ks.getenv("TREZO_BROKER_REJECT_WINDOW_MIN", "60")) * 60.0)
    except (TypeError, ValueError):
        return 3600.0


def _prune_rejects() -> None:
    cutoff = _time_ks.time() - _reject_window_s()
    while _broker_reject_ts and _broker_reject_ts[0] < cutoff:
        _broker_reject_ts.pop(0)


def record_broker_reject() -> int:
    _prune_rejects()
    _broker_reject_ts.append(_time_ks.time())
    return len(_broker_reject_ts)


def broker_reject_count() -> int:
    _prune_rejects()
    return len(_broker_reject_ts)


def reset_broker_rejects() -> None:
    _broker_reject_ts.clear()


# --- Session-scoped slippage tracker (2026-07-02) ---------------------
# Rules doc §1's slippage halt, deferred "until real (non-modeled) fills
# exist to measure" -- they exist now. The reconciler measures each fill
# (decision price vs the broker's avg fill) and feeds breaches here.
_slippage_breaches: list[float] = []


def record_fill_slippage(bps: float) -> int:
    """Track one measured fill's ADVERSE slippage (bps, positive = worse
    than the decision price). Counts a breach when it exceeds
    TREZO_SLIPPAGE_HALT_BPS (default 75). Returns the session breach count."""
    import os as _o
    try:
        limit = float(_o.getenv("TREZO_SLIPPAGE_HALT_BPS", "75"))
    except (TypeError, ValueError):
        limit = 75.0
    if bps > limit:
        _slippage_breaches.append(float(bps))
    return len(_slippage_breaches)


def slippage_breach_count() -> int:
    return len(_slippage_breaches)


def reset_slippage_breaches() -> None:
    _slippage_breaches.clear()


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def account_equity(account: dict, broker_equity: float | None = None) -> float:
    """Equity the loss limits are measured against.

    THE BUG THIS FIXES (2026-08-07). This used to be cash + vault ONLY --
    it excluded the market value of open positions. So on a fully deployed
    book, cash collapsed and the baseline collapsed with it: day-start
    equity was recording about $151 against a real account of $4,901, which
    turned the 3% daily loss limit into $4.52 instead of $147. Trading
    halted 33x earlier than intended, and the harder the agents worked the
    smaller their own limit became.

    The identical class of drift was found on 2026-07-02 in the allocation
    pockets (ledger $2.8k vs broker $4.8k, shrinking every pocket by 40%)
    and fixed there with effective_equity. This applies the same fix to the
    kill-switch, which was missed at the time.
    """
    if broker_equity and broker_equity > 0:
        return float(broker_equity)
    return _f(account.get("current_cash_usd")) + _f(account.get("vault_balance_usd"))


@dataclass
class KillSwitch:
    halted: bool
    scope: str | None       # 'day' | 'week' | 'session' | None
    reason: str | None


def period_updates(account: dict,
                   broker_equity: float | None = None) -> dict:
    """If the day or week has rolled over, return the column updates that
    re-baseline the account (and clear a scoped halt). Empty dict if there
    is nothing to roll."""
    upd: dict = {}
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    equity = account_equity(account, broker_equity)

    if str(account.get("last_reset_date") or "") != today.isoformat():
        upd["last_reset_date"] = today.isoformat()
        upd["day_start_equity_usd"] = round(equity, 2)
        upd["today_realized_pnl_usd"] = 0
        upd["consecutive_losses"] = 0
        upd["daily_target_hit_today"] = False
        if account.get("halt_scope") == "day":
            upd["trading_halted"] = False
            upd["halt_reason"] = None
            upd["halt_scope"] = None
    elif not account.get("day_start_equity_usd"):
        upd["day_start_equity_usd"] = round(equity, 2)

    if str(account.get("week_start_date") or "") != monday.isoformat():
        upd["week_start_date"] = monday.isoformat()
        upd["week_start_equity_usd"] = round(equity, 2)
        upd["week_realized_pnl_usd"] = 0
        if account.get("halt_scope") == "week":
            upd["trading_halted"] = False
            upd["halt_reason"] = None
            upd["halt_scope"] = None
    elif not account.get("week_start_equity_usd"):
        upd["week_start_equity_usd"] = round(equity, 2)

    return upd


def evaluate(account: dict, consec_limit: int = MAX_CONSECUTIVE_LOSSES) -> KillSwitch:
    """Evaluate every kill-switch for one (already period-rolled) account."""
    if account.get("trading_halted"):
        return KillSwitch(True, account.get("halt_scope"),
                          account.get("halt_reason") or "Trading halted")

    wse = _f(account.get("week_start_equity_usd"))
    wpnl = _f(account.get("week_realized_pnl_usd"))
    _tw = _f(account.get("_broker_equity"))
    if _tw > 0 and wse > 0 and wse < 0.5 * _tw:
        wse = _tw
    if wse > 0 and wpnl <= -WEEKLY_DRAWDOWN_PCT * wse:
        return KillSwitch(True, "week",
                          f"Weekly loss limit: down ${abs(wpnl):,.0f} "
                          f"({wpnl / wse * 100:.1f}%) this week")

    dse = _f(account.get("day_start_equity_usd"))
    dpnl = _f(account.get("today_realized_pnl_usd"))
    # STALENESS GUARD: a stored baseline far below true equity is left over
    # from a fully-deployed day and would halt on a trivial loss. Never let
    # it shrink the limit; the limit may only be as tight as real equity says.
    _true = _f(account.get("_broker_equity"))
    if _true > 0 and dse > 0 and dse < 0.5 * _true:
        dse = _true
    if dse > 0 and dpnl <= -DAILY_DRAWDOWN_PCT * dse:
        return KillSwitch(True, "day",
                          f"Daily loss limit: down ${abs(dpnl):,.0f} "
                          f"({dpnl / dse * 100:.1f}%) today")

    cl = int(account.get("consecutive_losses") or 0)
    if cl >= consec_limit:
        return KillSwitch(True, "day", f"{cl} losing trades in a row (limit {consec_limit})")

    rj = broker_reject_count()
    if rj >= MAX_BROKER_REJECTS:
        _mins = int(_reject_window_s() / 60)
        return KillSwitch(True, "session",
                          f"{rj} broker order rejects in the last {_mins} "
                          f"min - trading pauses until they age out")

    sb = slippage_breach_count()
    if sb >= MAX_SLIPPAGE_BREACHES:
        return KillSwitch(True, "session",
                          f"{sb} fills slipped past the limit this session "
                          f"- execution quality halt")

    return KillSwitch(False, None, None)


async def check_all(client) -> KillSwitch:
    """Roll periods, evaluate, and persist any new halt across all paper
    accounts. Returns the active halt (single-user assumption) or a
    not-halted KillSwitch."""
    if not client:
        return KillSwitch(False, None, None)

    def _fetch():
        return client.table("paper_accounts").select("*").execute()

    try:
        res = await asyncio.to_thread(_fetch)
    except Exception:  # noqa: BLE001
        return KillSwitch(False, None, None)

    active = KillSwitch(False, None, None)
    try:
        from app.runtime.settings import get_bot_settings
        consec_limit = int(get_bot_settings().consecutive_loss_limit)
    except Exception:  # noqa: BLE001
        consec_limit = MAX_CONSECUTIVE_LOSSES
    for acct in (res.data or []):
        _beq = 0.0
        try:
            from app.paper.allocation import effective_equity
            _beq = float(await effective_equity(str(acct.get("user_id") or "")) or 0)
        except Exception:  # noqa: BLE001
            _beq = 0.0
        if _beq > 0:
            acct = {**acct, "_broker_equity": _beq}
        upd = period_updates(acct, broker_equity=_beq or None)
        if upd:
            acct = {**acct, **upd}

            def _roll(uid=acct["user_id"], u=upd):
                return client.table("paper_accounts").update(u).eq("user_id", uid).execute()

            try:
                await asyncio.to_thread(_roll)
            except Exception:  # noqa: BLE001
                pass

        # Row-truth override (2026-07-02): the counters drift (WMT's -$61
        # bracket stop never rolled them; manual closes booked $0 until the
        # 7/1 fix). The kill-switch now SUMS this week's closed rows itself,
        # so it is correct regardless of which close path wrote the row.
        # 2026-07-07: cached 30s per user -- check_all runs per SIGNAL, and
        # during a veto storm the uncached sums hammered the nano DB.
        try:
            import time as _t
            _ck = str(acct.get("user_id"))
            _hit = _ROWSUM_CACHE.get(_ck)
            if _hit and (_t.time() - _hit[0]) < 30.0:
                acct = {**acct,
                        "week_realized_pnl_usd": _hit[1],
                        "today_realized_pnl_usd": _hit[2],
                        "consecutive_losses": max(
                            int(acct.get("consecutive_losses") or 0), _hit[3])}
                raise _RowsumCached()
            _today_s = date.today().isoformat()
            _monday_s = (date.today()
                         - timedelta(days=date.today().weekday())).isoformat()

            def _rows(uid=acct["user_id"], m=_monday_s):
                return (client.table("paper_positions")
                        .select("realized_pnl_usd, exit_at")
                        .eq("user_id", uid)
                        .gte("exit_at", m)
                        .like("status", "closed%")
                        .order("exit_at", desc=True)
                        .limit(500).execute())
            _rr = (await asyncio.to_thread(_rows)).data or []
            _wk = sum(float(x.get("realized_pnl_usd") or 0) for x in _rr)
            _dy = sum(float(x.get("realized_pnl_usd") or 0) for x in _rr
                      if str(x.get("exit_at") or "")[:10] == _today_s)
            _streak = 0
            for x in _rr:
                _p = float(x.get("realized_pnl_usd") or 0)
                if _p < 0:
                    _streak += 1
                elif _p > 0:
                    break
            acct = {**acct,
                    "week_realized_pnl_usd": round(_wk, 2),
                    "today_realized_pnl_usd": round(_dy, 2),
                    "consecutive_losses": max(
                        int(acct.get("consecutive_losses") or 0), _streak)}
            _ROWSUM_CACHE[_ck] = (_t.time(), round(_wk, 2), round(_dy, 2),
                                  _streak)
        except _RowsumCached:
            pass
        except Exception:  # noqa: BLE001
            pass

        ks = evaluate(acct, consec_limit)
        if ks.halted:
            if not acct.get("trading_halted") and ks.scope in ("day", "week"):
                def _persist(uid=acct["user_id"], k=ks):
                    return client.table("paper_accounts").update({
                        "trading_halted": True,
                        "halt_reason": k.reason,
                        "halt_scope": k.scope,
                        "halted_at": datetime.now(timezone.utc).isoformat(),
                    }).eq("user_id", uid).execute()

                try:
                    await asyncio.to_thread(_persist)
                except Exception:  # noqa: BLE001
                    pass
            active = ks
    return active


# --- QW6: per-coin crypto daily loss limit -----------------------------

NUM_CRYPTO_COINS = 3                 # XRP / ETH / SOL
PER_COIN_DAILY_LOSS_PCT = 0.10       # of a coin's slice of the crypto budget


async def coin_loss_halt(client, ticker: str) -> str | None:
    """Per-coin daily loss limit (TREZO_NOVA_BOT_TRADE_RULES, Section 1).

    A crypto coin is benched for the rest of the UTC day once its realized
    losses on that coin today reach 10% of the coin's slice of the crypto
    allocation budget. This sits alongside the account-wide kill-switches
    so one bad coin can be stopped without halting the others. Returns a
    veto reason string, or None when the coin is clear.
    """
    if not client:
        return None
    sym = (ticker or "").upper()

    # Today's realized P&L on this coin (UTC day).
    try:
        start = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00+00:00")

        def _q():
            return (client.table("paper_positions")
                    .select("realized_pnl_usd")
                    .eq("ticker", sym)
                    .eq("asset_type", "crypto")
                    .neq("status", "open")
                    .gte("exit_at", start)
                    .execute())
        res = await asyncio.to_thread(_q)
        realized = sum(_f(r.get("realized_pnl_usd")) for r in (res.data or []))
    except Exception:  # noqa: BLE001
        return None
    if realized >= 0:
        return None

    # The coin's slice of the crypto allocation budget.
    try:
        def _acct():
            return client.table("paper_accounts").select("*").limit(1).execute()
        ares = await asyncio.to_thread(_acct)
        acct = (ares.data or [None])[0]
        if not acct:
            return None
        equity = account_equity(acct)
        from app.paper.allocation import build_allocation
        from app.runtime.settings import get_bot_settings
        cfg = get_bot_settings()
        alloc = build_allocation(equity, posture_setting=cfg.account_posture,
                                 overrides=cfg.allocation_overrides)
        crypto_budget = float(alloc.budgets.get("crypto", 0.0))
    except Exception:  # noqa: BLE001
        return None
    if crypto_budget <= 0:
        return None

    limit = PER_COIN_DAILY_LOSS_PCT * (crypto_budget / NUM_CRYPTO_COINS)
    if limit > 0 and -realized >= limit:
        return (f"{sym} per-coin daily loss limit: down "
                f"${-realized:,.0f} today (limit ${limit:,.0f})")
    return None
