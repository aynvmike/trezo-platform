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


# --- Session-scoped broker-reject counter (in-process) ----------------
_broker_rejects = 0


def record_broker_reject() -> int:
    global _broker_rejects
    _broker_rejects += 1
    return _broker_rejects


def broker_reject_count() -> int:
    return _broker_rejects


def reset_broker_rejects() -> None:
    global _broker_rejects
    _broker_rejects = 0


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def account_equity(account: dict) -> float:
    return _f(account.get("current_cash_usd")) + _f(account.get("vault_balance_usd"))


@dataclass
class KillSwitch:
    halted: bool
    scope: str | None       # 'day' | 'week' | 'session' | None
    reason: str | None


def period_updates(account: dict) -> dict:
    """If the day or week has rolled over, return the column updates that
    re-baseline the account (and clear a scoped halt). Empty dict if there
    is nothing to roll."""
    upd: dict = {}
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    equity = account_equity(account)

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
    if wse > 0 and wpnl <= -WEEKLY_DRAWDOWN_PCT * wse:
        return KillSwitch(True, "week",
                          f"Weekly loss limit: down ${abs(wpnl):,.0f} "
                          f"({wpnl / wse * 100:.1f}%) this week")

    dse = _f(account.get("day_start_equity_usd"))
    dpnl = _f(account.get("today_realized_pnl_usd"))
    if dse > 0 and dpnl <= -DAILY_DRAWDOWN_PCT * dse:
        return KillSwitch(True, "day",
                          f"Daily loss limit: down ${abs(dpnl):,.0f} "
                          f"({dpnl / dse * 100:.1f}%) today")

    cl = int(account.get("consecutive_losses") or 0)
    if cl >= consec_limit:
        return KillSwitch(True, "day", f"{cl} losing trades in a row (limit {consec_limit})")

    rj = broker_reject_count()
    if rj >= MAX_BROKER_REJECTS:
        return KillSwitch(True, "session",
                          f"{rj} broker order rejects this session")

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
        upd = period_updates(acct)
        if upd:
            acct = {**acct, **upd}

            def _roll(uid=acct["user_id"], u=upd):
                return client.table("paper_accounts").update(u).eq("user_id", uid).execute()

            try:
                await asyncio.to_thread(_roll)
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
