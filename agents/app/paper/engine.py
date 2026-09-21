"""Paper trading engine.

Handles the actual mechanics of simulated trading:
- Read user's paper_accounts (cash + vault)
- Open a paper_positions row when an `execute` signal fires
- Close positions when stop/target hit (called from the monitor)
- Apply slippage (5 bps) + commission ($0 stocks/crypto for now)
- Update cash + realized P&L

Real-broker execution lives in Phase 9; this module is the in-memory
ledger that drives Phase 6.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from app.config import get_settings
from app.paper.no_price_stop import is_no_price_stop as _is_no_price_stop
from app.paper.no_price_stop import payload_is_no_price_stop as _payload_nps


# ---- Configurable parameters ----------------------------------------------

SLIPPAGE_BPS = 5            # 0.05% on every fill (entry + exit)
STOCK_COMMISSION = 0.0      # Robinhood-style free
CRYPTO_COMMISSION_BPS = 26  # Kraken taker ~0.26%/side (Mike 2026-06-15: real modeled fee, tunable here)


# ---- Supabase client (lazy) -----------------------------------------------

_client = None


def _supabase():
    global _client
    if _client is not None:
        return _client
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_role_key:
        return None
    try:
        from supabase import create_client
        _client = create_client(settings.supabase_url, settings.supabase_service_role_key)
        return _client
    except Exception:
        return None


@dataclass
class FillResult:
    """Returned by open_position and close_position."""
    ok: bool
    position_id: Optional[str] = None
    fill_price: float = 0.0
    realized_pnl_usd: float = 0.0
    error: Optional[str] = None
    pending: bool = False
    duplicate: bool = False
    remaining_qty: float = 0.0
    fees_complete: bool = False
    pnl_provisional: bool = True
    broker_order_id: Optional[str] = None


# ---- Helpers --------------------------------------------------------------


def _payload_dict(value: Any) -> dict:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return {}
    return dict(value) if isinstance(value, dict) else {}


def apply_slippage(price: float, side: str, action: str) -> float:
    """Slippage model: 5 bps against you on every fill."""
    bps = SLIPPAGE_BPS / 10_000.0
    if (side == "long" and action == "open") or (side == "short" and action == "close"):
        return price * (1 + bps)
    return price * (1 - bps)


def commission(asset_type: str, notional: float) -> float:
    if asset_type == "crypto":
        return notional * (CRYPTO_COMMISSION_BPS / 10_000.0)
    return STOCK_COMMISSION


def calc_quantity(account_cash: float, entry_price: float, stop_price: float, risk_pct: float) -> float:
    """Position size from risk-per-trade math.

    Risk amount = account_cash * risk_pct (e.g. 5%).
    Stop distance = |entry - stop|
    Quantity = risk_amount / stop_distance

    Falls back to a tiny position if stop_distance is 0 or invalid.
    """
    if entry_price <= 0 or stop_price <= 0:
        return 0.0
    stop_distance = abs(entry_price - stop_price)
    if stop_distance == 0:
        return 0.0
    risk_amount = account_cash * risk_pct
    qty = risk_amount / stop_distance
    return max(0.0, qty)


# ---- Account helpers ------------------------------------------------------


async def get_account(user_id: str) -> Optional[dict[str, Any]]:
    client = _supabase()
    if not client:
        return None

    def _sync():
        return (
            client.table("paper_accounts")
            .select("*")
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )

    res = await asyncio.to_thread(_sync)
    return res.data if res else None


# ---- Open position --------------------------------------------------------


async def open_position(
    user_id: str,
    ticker: str,
    asset_type: str,
    side: str,
    market_price: float,
    stop_pct: float = 0.05,
    target_pct: float = 0.10,
    risk_pct: float = 0.05,
    strategy: str = "default",
    source_payload: Optional[dict] = None,
    max_notional: Optional[float] = None,
) -> FillResult:
    """Open a simulated paper position.

    - Fetches user's current cash from paper_accounts
    - Sizes the position using the 5%-risk rule
    - Applies entry slippage
    - Inserts a paper_positions row with status='open'
    - Deducts notional + commission from current_cash
    """
    client = _supabase()
    if not client:
        return FillResult(ok=False, error="Supabase not configured")

    account = await get_account(user_id)
    if not account:
        return FillResult(ok=False, error=f"No paper account for {user_id}")

    cash = float(account["current_cash_usd"])
    if cash <= 0:
        return FillResult(ok=False, error="No buying power")

    # Entry price with slippage
    fill_price = apply_slippage(market_price, side, "open")
    # Visibility pack (2026-07-01): show the slippage rule working on every
    # modeled fill. File-append only; never raises.
    try:
        from app.agents.activity_log import record as _arec
        _arec("fill_open_modeled", ticker,
              reason=(f"{side} fill {fill_price:.6g} vs mkt {market_price:.6g} "
                      f"({SLIPPAGE_BPS}bps slippage applied)"),
              extra={"user_id": str(user_id), "asset_type": asset_type})
    except Exception:  # noqa: BLE001
        pass

    # Compute stop + target prices
    if side == "long":
        stop_price   = fill_price * (1 - stop_pct)
        target_price = fill_price * (1 + target_pct)
    else:
        stop_price   = fill_price * (1 + stop_pct)
        target_price = fill_price * (1 - target_pct)

    # Phase 8a: account-aware sizing. Equity (not just cash) drives the
    # risk math, so the position range scales with account size.
    from app.paper.sizing import plan_position
    equity = cash + float(account.get("vault_balance_usd") or 0)
    # Coverage trades stay SMALL (Mike 2026-07-02): shrink risk so the
    # modeled test position lands near TREZO_COVERAGE_TRADE_USD notional.
    if (source_payload or {}).get("coverage_trade"):
        try:
            import os as _osc
            _cov = float(_osc.getenv("TREZO_COVERAGE_TRADE_USD", "150"))
            _rp = (_cov * float(stop_pct)) / max(equity, 1.0)
            risk_pct = min(float(risk_pct), max(_rp, 0.0005))
        except Exception:  # noqa: BLE001
            pass
    # Margin allowance (Mike 2026-07-17): stock entries may spend past
    # cash into margin, bounded by a closed form: with a long book,
    # deployed = equity - cash, so per-entry spendable =
    # cash + (TREZO_MAX_DEPLOY_X - 1) x equity keeps total deployment
    # under TREZO_MAX_DEPLOY_X x equity (default 1.25x) with no broker
    # call -- as margin gets used cash goes negative and the allowance
    # self-shrinks to zero at the ceiling. Crypto/forex stay cash-only
    # (no margin at the venue). The Risk Manager charges +8 TCS while
    # entries sit in margin territory: leverage is earned, never default.
    _spend = cash
    if asset_type not in ("crypto", "forex"):
        try:
            import os as _osm
            _deploy_x = float(_osm.getenv("TREZO_MAX_DEPLOY_X", "1.25"))
        except (TypeError, ValueError):
            _deploy_x = 1.25
        _spend = cash + max(_deploy_x - 1.0, 0.0) * max(equity, 0.0)
    plan = plan_position(
        equity=equity,
        entry_price=fill_price,
        stop_price=stop_price,
        target_price=target_price,
        risk_pct=risk_pct,
        user_id=user_id,        # this book's R:R floor, not the global row
        asset_type=asset_type,
        buying_power=(min(_spend, max_notional) if max_notional is not None else _spend),
    )
    if not plan.ok:
        return FillResult(ok=False, error=plan.reject_reason or "Sizing rejected the trade")
    qty = plan.quantity

    # Crypto fractional; stocks rounded to share count
    if asset_type != "crypto":
        qty = max(1.0, float(int(qty)))  # at least 1 share if cash allows

    notional = qty * fill_price
    if notional > cash:
        # Scale down to fit available cash
        qty = max(0.0, cash / fill_price * 0.99)
        if asset_type != "crypto":
            qty = float(int(qty))
        if qty <= 0:
            return FillResult(ok=False, error="Not enough cash for one share")
        notional = qty * fill_price

    fee = commission(asset_type, notional)
    new_cash = cash - notional - fee

    def _sync_insert():
        return (
            client.table("paper_positions")
            .insert({
                "user_id": user_id,
                "ticker": ticker.upper(),
                "asset_type": asset_type,
                "side": side,
                "quantity": qty,
                "entry_price": fill_price,
                "stop_price": stop_price,
                "target_price": target_price,
                "status": "open",
                "fees_usd": fee,
                "strategy": strategy,
                "source_payload": source_payload or {},
            })
            .execute()
        )

    def _sync_update_cash():
        return (
            client.table("paper_accounts")
            .update({"current_cash_usd": new_cash, "updated_at": datetime.now(timezone.utc).isoformat()})
            .eq("user_id", user_id)
            .execute()
        )

    try:
        ins = await asyncio.to_thread(_sync_insert)
        await asyncio.to_thread(_sync_update_cash)
        pos_id = (ins.data or [{}])[0].get("id") if ins.data else None
        return FillResult(ok=True, position_id=pos_id, fill_price=fill_price)
    except Exception as e:
        return FillResult(ok=False, error=str(e))


# ---- Close position -------------------------------------------------------


async def close_position(
    user_id: str,
    position_id: str,
    market_price: float,
    reason: str = "manual",
) -> FillResult:
    """Close an open paper position.

    Updates the row with exit_price, realized P&L, status. Adds proceeds
    back to current_cash. Updates today_realized_pnl_usd + ytd_realized_pnl_usd.
    """
    client = _supabase()
    if not client:
        return FillResult(ok=False, error="Supabase not configured")

    def _sync_get():
        return (
            client.table("paper_positions")
            .select("*")
            .eq("id", position_id)
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )

    res = await asyncio.to_thread(_sync_get)
    pos = res.data if res else None
    if not pos or pos.get("status") != "open":
        return FillResult(ok=False, error="Position not open")
    if str(pos.get("broker") or "").strip().lower() == "alpaca":
        return FillResult(ok=False, position_id=position_id, pending=True,
                          error="Broker-managed position requires confirmed fill accounting")

    side  = pos["side"]
    qty   = float(pos["quantity"])
    entry = float(pos["entry_price"])
    asset_type = pos["asset_type"]

    # Exit with slippage
    fill_price = apply_slippage(market_price, side, "close")
    notional = qty * fill_price
    fee = commission(asset_type, notional)

    if side == "long":
        gross_pnl = qty * (fill_price - entry)
    else:
        gross_pnl = qty * (entry - fill_price)
    pnl = gross_pnl - fee - float(pos.get("fees_usd", 0))
    # Visibility pack (2026-07-01): closes show slippage + fee + net P/L.
    try:
        from app.agents.activity_log import record as _arec
        _arec("fill_close_modeled", str(pos.get("ticker") or "?"),
              strategy=str(pos.get("strategy") or "") or None,
              reason=(f"{reason}: fill {fill_price:.6g} vs mkt {market_price:.6g} "
                      f"({SLIPPAGE_BPS}bps slip + ${fee:.2f} fee), pnl {pnl:+.2f}"),
              extra={"user_id": str(user_id), "asset_type": asset_type})
    except Exception:  # noqa: BLE001
        pass

    # Map reason → status
    status_map = {
        "stop":   "closed_stop",
        "target": "closed_target",
        "time":   "closed_time",
        "eod":    "closed_eod",
        "manual": "closed_manual",
    }
    status = status_map.get(reason, "closed_manual")

    def _sync_close():
        return (
            client.table("paper_positions")
            .update({
                "status": status,
                "exit_price": fill_price,
                "exit_at": datetime.now(timezone.utc).isoformat(),
                "realized_pnl_usd": pnl,
                "fees_usd": float(pos.get("fees_usd", 0)) + fee,
            })
            .eq("id", position_id)
            .execute()
        )

    await asyncio.to_thread(_sync_close)

    # Update account cash + P&L
    account = await get_account(user_id)
    if account:
        new_cash = float(account["current_cash_usd"]) + notional - fee
        new_today = float(account["today_realized_pnl_usd"]) + pnl
        new_ytd   = float(account["ytd_realized_pnl_usd"])   + pnl
        # Kill-switch counters (Phase 8c): a losing trade extends the
        # streak, a winning trade resets it; weekly realized P&L accrues.
        prev_consec = int(account.get("consecutive_losses") or 0)
        new_consec = (prev_consec + 1) if pnl < 0 else 0
        new_week_pnl = float(account.get("week_realized_pnl_usd") or 0) + pnl

        def _sync_update_account():
            return (
                client.table("paper_accounts")
                .update({
                    "current_cash_usd": new_cash,
                    "today_realized_pnl_usd": new_today,
                    "ytd_realized_pnl_usd": new_ytd,
                    "consecutive_losses": new_consec,
                    "week_realized_pnl_usd": round(new_week_pnl, 2),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
                .eq("user_id", user_id)
                .execute()
            )

        await asyncio.to_thread(_sync_update_account)

    # Phase 13/14 — learning-loop recorder. Writes one trade_outcomes
    # row capturing entry context + outcome. Never blocks the close.
    try:
        from app.learning.outcomes import record_paper_close
        await record_paper_close(
            user_id=user_id,
            position_id=position_id,
            ticker=pos.get("ticker"),
            asset_type=asset_type,
            side=side,
            strategy=pos.get("strategy"),
            direction=(pos.get("source_payload") or {}).get("direction"),
            entry_price=entry,
            exit_price=fill_price,
            quantity=qty,
            realized_pnl_usd=pnl,
            exit_reason=reason,
            status=status,
            opened_at=pos.get("entry_at"),
            closed_at=datetime.now(timezone.utc).isoformat(),
            source_payload=pos.get("source_payload"),
        )
    except Exception:  # noqa: BLE001
        # Bookkeeping should never block the close.
        pass

    return FillResult(ok=True, position_id=position_id, fill_price=fill_price, realized_pnl_usd=pnl)


# ---- Daily reset ----------------------------------------------------------


async def close_partial_position(
    user_id: str,
    position_id: str,
    fraction: float,
    market_price: float,
    reason: str = "partial",
) -> FillResult:
    """Sell a FRACTION (0 < f < 1) of an open position. The position
    row stays open with reduced quantity. Capital recycling primitive
    Mike 2026-06-01: when the decayed_thesis alert fires with
    recommendation 'trim_partial', this is what runs.

    - Applies slippage + commission to the closed slice only.
    - Account cash += partial proceeds. Today/YTD realized P&L += slice P&L.
    - Writes a trade_outcomes row tagged exit_reason='partial' so the
      learning loop tracks the trim as its own event.
    - The remaining quantity keeps its original entry price, stop,
      target - the rest of the trade continues as if nothing happened.

    Returns FillResult with realized_pnl_usd = the slice's P&L.
    """
    # Validate fraction sits in the open interval (0, 1).
    try:
        f = float(fraction)
    except (TypeError, ValueError):
        return FillResult(ok=False, error="Fraction must be a number")
    if not (0.0 < f < 1.0):
        return FillResult(ok=False, error="Fraction must be between 0 and 1 exclusive")

    client = _supabase()
    if not client:
        return FillResult(ok=False, error="Supabase not configured")

    def _sync_get():
        return (
            client.table("paper_positions")
            .select("*")
            .eq("id", position_id)
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )

    res = await asyncio.to_thread(_sync_get)
    pos = res.data if res else None
    if not pos or pos.get("status") != "open":
        return FillResult(ok=False, error="Position not open")
    if str(pos.get("broker") or "").strip().lower() == "alpaca":
        return FillResult(ok=False, position_id=position_id, pending=True,
                          error="Broker-managed position requires confirmed fill accounting")

    side = pos["side"]
    total_qty = float(pos["quantity"])
    entry = float(pos["entry_price"])
    asset_type = pos["asset_type"]

    # Slice the position. For stocks we round down to whole shares.
    raw_slice = total_qty * f
    if asset_type != "crypto":
        slice_qty = float(int(raw_slice))
    else:
        slice_qty = raw_slice
    if slice_qty <= 0:
        return FillResult(ok=False, error="Slice rounds to zero - position too small to trim")
    if slice_qty >= total_qty:
        return FillResult(ok=False, error="Slice >= total. Use close_position for a full close")

    remaining_qty = total_qty - slice_qty
    if asset_type != "crypto" and remaining_qty < 1:
        return FillResult(ok=False,
                          error="Trimming would leave less than 1 share. Use full close instead")

    # Exit price with slippage on the slice.
    fill_price = apply_slippage(market_price, side, "close")
    slice_notional = slice_qty * fill_price
    slice_fee = commission(asset_type, slice_notional)

    if side == "long":
        slice_gross = slice_qty * (fill_price - entry)
    else:
        slice_gross = slice_qty * (entry - fill_price)
    slice_pnl = slice_gross - slice_fee

    def _sync_trim():
        # Keep status='open'. Reduce quantity. Accumulate fees.
        return (
            client.table("paper_positions")
            .update({
                "quantity": remaining_qty,
                "fees_usd": float(pos.get("fees_usd", 0)) + slice_fee,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            .eq("id", position_id)
            .execute()
        )

    try:
        await asyncio.to_thread(_sync_trim)
    except Exception as e:  # noqa: BLE001
        return FillResult(ok=False, error=f"DB update failed: {e}")

    # Account counters: cash + today/YTD/weekly realized P&L.
    account = await get_account(user_id)
    if account:
        new_cash = float(account["current_cash_usd"]) + slice_notional - slice_fee
        new_today = float(account["today_realized_pnl_usd"]) + slice_pnl
        new_ytd = float(account["ytd_realized_pnl_usd"]) + slice_pnl
        # Partial close: do NOT bump consecutive_losses on a slice win;
        # only a full close-on-stop should count toward the streak.
        new_week_pnl = float(account.get("week_realized_pnl_usd") or 0) + slice_pnl

        def _sync_update_account():
            return (
                client.table("paper_accounts")
                .update({
                    "current_cash_usd": new_cash,
                    "today_realized_pnl_usd": new_today,
                    "ytd_realized_pnl_usd": new_ytd,
                    "week_realized_pnl_usd": round(new_week_pnl, 2),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
                .eq("user_id", user_id)
                .execute()
            )

        await asyncio.to_thread(_sync_update_account)

    # Learning loop: write a trade_outcomes row tagged 'partial' so the
    # post-mortem ledger sees the trim as its own event. Best-effort.
    try:
        from app.learning.outcomes import record_paper_close
        await record_paper_close(
            user_id=user_id,
            position_id=position_id,
            ticker=pos.get("ticker"),
            asset_type=asset_type,
            side=side,
            strategy=pos.get("strategy"),
            direction=(pos.get("source_payload") or {}).get("direction"),
            entry_price=entry,
            exit_price=fill_price,
            quantity=slice_qty,
            realized_pnl_usd=slice_pnl,
            exit_reason=reason,                # 'partial' by default
            status="partial_trim",
            opened_at=pos.get("entry_at"),
            closed_at=datetime.now(timezone.utc).isoformat(),
            source_payload=pos.get("source_payload"),
        )
    except Exception:  # noqa: BLE001
        pass

    return FillResult(
        ok=True,
        position_id=position_id,
        fill_price=fill_price,
        realized_pnl_usd=slice_pnl,
    )


async def reset_daily_counters(user_id: str) -> None:
    """Called once per day (when the date rolls over)."""
    client = _supabase()
    if not client:
        return

    def _sync():
        return (
            client.table("paper_accounts")
            .update({
                "today_realized_pnl_usd": 0,
                "daily_target_hit_today": False,
                "last_reset_date": datetime.now(timezone.utc).date().isoformat(),
            })
            .eq("user_id", user_id)
            .execute()
        )

    await asyncio.to_thread(_sync)


# ---- Daily Profit Lock ----------------------------------------------------


async def check_and_lock_profit(user_id: str) -> Optional[dict]:
    """If today's P&L >= user's daily target and not already locked today,
    transfer the target amount from cash to vault. Returns the lock event
    or None if no action."""
    client = _supabase()
    if not client:
        return None

    # Get user's daily target from profile
    def _sync_profile():
        return (
            client.table("profiles")
            .select("daily_profit_target_usd")
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )

    p = await asyncio.to_thread(_sync_profile)
    if not p or not p.data:
        return None
    target = float(p.data.get("daily_profit_target_usd") or 0)
    if target <= 0:
        return None

    account = await get_account(user_id)
    if not account:
        return None
    if account["daily_target_hit_today"]:
        return None  # already locked today
    today = float(account["today_realized_pnl_usd"])
    if today < target:
        return None

    new_cash  = float(account["current_cash_usd"]) - target
    new_vault = float(account["vault_balance_usd"]) + target

    def _sync_update():
        return (
            client.table("paper_accounts")
            .update({
                "current_cash_usd": new_cash,
                "vault_balance_usd": new_vault,
                "daily_target_hit_today": True,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            .eq("user_id", user_id)
            .execute()
        )

    def _sync_tx():
        return (
            client.table("paper_vault_transactions")
            .insert({
                "user_id": user_id,
                "amount_usd": target,
                "kind": "profit_lock",
                "description": f"Daily target ${target:.2f} reached. Auto-locked.",
            })
            .execute()
        )

    await asyncio.to_thread(_sync_update)
    await asyncio.to_thread(_sync_tx)
    return {"amount": target, "today_pnl": today, "vault_balance": new_vault}


# ---- External-broker position record (Phase 8b) ---------------------------


async def record_external_position(
    user_id: str,
    ticker: str,
    asset_type: str,
    side: str,
    quantity: float,
    entry_price: float,
    stop_price: float,
    target_price: float,
    strategy: str,
    broker: str,
    broker_order_id: Optional[str],
    source_payload: Optional[dict] = None,
    entry_at: Optional[str] = None,
) -> FillResult:
    """Insert a tracking row for a position executed on an external broker
    (e.g. Alpaca). No cash math here - the broker holds the real account;
    this row exists so Trezo's dashboard and monitor can see the position.

    `entry_at` (2026-09-03, the XDTE clock): WHEN the position was bought,
    as the broker's own receipt records it. Optional and OFF by default in
    the sense that omitting it reproduces the old behaviour exactly -- the
    column is left out of the insert and Postgres defaults it to now().
    That default is the defect: an adopted row was stamped with the moment
    the reconciler NOTICED the position (row 37d36b9e: entry_at ==
    created_at == updated_at == 14:20:53.914599Z, while the four fills that
    built it landed 13:30:49 .. 13:33:52). entry_at drives every time-based
    exit and the staleness rules, so every adoption silently reset a
    position's age to zero. Callers that can produce a RECEIPT -- see
    app/paper/entry_receipt.py -- pass it; callers that cannot must pass
    nothing rather than a guess.

    The MERGE below deliberately ignores `entry_at`. A position's entry is
    the FIRST fill that built it, so folding an add into an open row must
    never move that row's clock: forward would hide its age, backward
    would age it into an exit it has not earned. One position, one entry,
    set when the row is created.

    MERGES an add into the existing open row for the same ticker+side
    (Mike 2026-07-28: "the multiple entries of crypto should be changed
    to show the purchase changing the average entry and cost of the
    previous entry... such as a normal book would"). Crypto DCA used to
    open a NEW row per add, so one coin showed up three times with three
    entry prices -- Alpaca itself reports ONE position with a weighted
    average, and so should Trezo. The merged row keeps the widest
    protection of the two (lowest stop / highest target for a long) so
    an add can never tighten a stop into the market."""
    client = _supabase()
    if not client:
        return FillResult(ok=False, error="Supabase not configured")

    # --- weighted-average merge -------------------------------------
    try:
        def _find_open():
            # vf:no-price-stop-monitor: source_payload (and strategy) ride
            # along so the boundary check below can read the flag off
            # the EXISTING row; without them every open row read as
            # unflagged and the check was built but never bound.
            return (client.table("paper_positions")
                    .select("id, quantity, entry_price, stop_price, "
                            "target_price, peak_price, source_payload, "
                            "strategy")
                    .eq("user_id", user_id).eq("ticker", ticker.upper())
                    .eq("side", side).eq("status", "open")
                    .order("entry_at", desc=False).limit(1).execute())
        _ex = (await asyncio.to_thread(_find_open)).data or []
    except Exception:  # noqa: BLE001
        _ex = []
    # vf:no-price-stop-monitor (audit 2026-09-01): the merge keyed on
    # user/ticker/side/status only and patched quantity/entry/stop/target
    # onto the EXISTING row, so an ordinary add of the same ticker into a
    # book holding a flagged no_price_stop ladder row was folded into
    # that row -- which kept the flag and so IGNORED the add's stop (the
    # added shares sat unprotected under a flag they never carried) --
    # and a ladder add into an ordinary row was folded into the unflagged
    # row and price-managed after all (the lane's contract silently
    # lost). The flag is a property of the shares' contract, not of the
    # ticker: when the two sides disagree, this is a DIFFERENT position
    # and gets its own row. Same predicate the monitor uses.
    if _ex and (_is_no_price_stop(_ex[0])
                != _payload_nps(source_payload or {})):
        try:
            from app.agents.activity_log import record as _brec
            _brec("position_merge_refused", ticker.upper(),
                  strategy=strategy,
                  reason=("add not merged: the open row and the add "
                          "disagree on no_price_stop (existing "
                          f"{'flagged' if _is_no_price_stop(_ex[0]) else 'ordinary'}, "
                          f"add {'flagged' if _payload_nps(source_payload or {}) else 'ordinary'}) "
                          "- a screen-managed hold and a price-stopped "
                          "position are two positions, so this opens "
                          "its own row"),
                  extra={"user_id": str(user_id),
                         "existing_position_id": str(_ex[0].get("id")),
                         "existing_strategy": str(_ex[0].get("strategy") or "")})
        except Exception:  # noqa: BLE001
            pass
        _ex = []          # fall through to a fresh insert
    if _ex:
        _row = _ex[0]
        try:
            _q0 = float(_row.get("quantity") or 0)
            _e0 = float(_row.get("entry_price") or 0)
            _q1 = float(quantity or 0)
            _e1 = float(entry_price or 0)
            if _q0 > 0 and _q1 > 0 and _e0 > 0 and _e1 > 0:
                _qn = _q0 + _q1
                _en = round(((_q0 * _e0) + (_q1 * _e1)) / _qn, 8)
                _long = str(side).lower() == "long"
                _s0 = float(_row.get("stop_price") or 0) or None
                _t0 = float(_row.get("target_price") or 0) or None
                _sn = (min(_s0, stop_price) if (_s0 and stop_price and _long)
                       else max(_s0, stop_price) if (_s0 and stop_price)
                       else (stop_price or _s0))
                _tn = (max(_t0, target_price) if (_t0 and target_price and _long)
                       else min(_t0, target_price) if (_t0 and target_price)
                       else (target_price or _t0))
                _old_payload = _payload_dict(_row.get("source_payload"))
                _add_payload = _payload_dict(source_payload)
                _verified = (_old_payload.get("entry_basis_verified") is True
                             and _add_payload.get("entry_basis_verified") is True)
                _fees_known = (_old_payload.get("entry_fees_known") is True
                               and _add_payload.get("entry_fees_known") is True)
                _basis_keys = ("broker_order_id", "entry_basis_verified", "entry_fees_known",
                               "entry_status", "entry_price_source", "broker_entry_notional",
                               "broker_entry_filled_qty", "broker_entry_filled_avg_price",
                               "broker_entry_filled_at", "entry_cost_includes_measured_coin_fee")
                _components = _old_payload.get("broker_entry_components")
                _components = list(_components) if isinstance(_components, list) else []
                if not _components:
                    _components.append({k: _old_payload[k] for k in _basis_keys if k in _old_payload})
                _components.append({**{k: _add_payload[k] for k in _basis_keys if k in _add_payload},
                                    "broker_order_id": broker_order_id})
                # Keep strategy/protection metadata, but never let a verified
                # old lot certify a provisional add. Per-entry receipts remain
                # available without presenting the first lot as the whole basis.
                _merged_payload = {k: v for k, v in _old_payload.items()
                                   if k not in ("broker_entry_notional", "broker_entry_filled_qty",
                                                "broker_entry_filled_avg_price")}
                _merged_payload.update({"entry_basis_verified": _verified,
                                        "entry_fees_known": _fees_known,
                                        "entry_price_source": "weighted_broker_fills" if _verified else "mixed_provisional",
                                        "entry_status": "filled" if (_old_payload.get("entry_status") == "filled"
                                                                     and _add_payload.get("entry_status") == "filled")
                                                        else "pending_verification",
                                        "broker_entry_components": _components})
                _patch = {"quantity": _qn, "entry_price": _en,
                          "stop_price": _sn, "target_price": _tn,
                          "source_payload": _merged_payload}

                def _do_merge():
                    query = (client.table("paper_positions").update(_patch)
                             .eq("id", _row["id"]).eq("user_id", user_id).eq("status", "open")
                             .eq("quantity", _row["quantity"]).eq("entry_price", _row["entry_price"]))
                    if _row.get("source_payload") is None:
                        query = query.is_("source_payload", "null")
                    else:
                        query = query.eq("source_payload", json.dumps(_row["source_payload"]))
                    return query.execute()
                try:
                    _merged = await asyncio.to_thread(_do_merge)
                    if not isinstance(_merged.data, list) or len(_merged.data) != 1:
                        return FillResult(ok=False, position_id=_row.get("id"), pending=True,
                                          error="Position changed during broker entry merge; reconcile the confirmed entry")
                except Exception:
                    return FillResult(ok=False, position_id=_row.get("id"), pending=True,
                                      error="Broker entry merge unverified; reconcile the confirmed entry")
                try:
                    from app.agents.activity_log import record as _mrec
                    _mrec("position_merged", ticker.upper(),
                          strategy=strategy,
                          reason=(f"add of {_q1:g} @ ${_e1:,.4f} merged into "
                                  f"the open position: {_q0:g} -> {_qn:g} "
                                  f"units, average entry ${_e0:,.4f} -> "
                                  f"${_en:,.4f} (one position, one basis - "
                                  f"the way a broker book reads)"),
                          extra={"user_id": str(user_id),
                                 "position_id": str(_row.get("id"))})
                except Exception:  # noqa: BLE001
                    pass
                return FillResult(ok=True, position_id=_row.get("id"),
                                  fill_price=entry_price)
        except Exception:  # noqa: BLE001
            pass   # fall through to a normal insert

    def _sync_insert():
        _row = {
            "user_id": user_id,
            "ticker": ticker.upper(),
            "asset_type": asset_type,
            "side": side,
            "quantity": quantity,
            "entry_price": entry_price,
            "stop_price": stop_price,
            "target_price": target_price,
            "status": "open",
            "strategy": strategy,
            # Fixed 2026-06-11 PM: broker/broker_order_id were ONLY
            # stored inside source_payload, never in their real
            # columns -- so every Alpaca-routed row landed as
            # broker="paper" and the Position Monitor's entire
            # Alpaca branch (bracket reconcile, time stops, crypto
            # exits, broker-aware close) skipped it. AAPL was held
            # live at Alpaca while Trezo managed it as internal
            # paper because of this.
            "broker": broker,
            "broker_order_id": broker_order_id,
            "source_payload": {
                **(source_payload or {}),
                "broker": broker,
                "broker_order_id": broker_order_id,
            },
        }
        # Omitted, not None: sending entry_at=None would OVERRIDE the
        # column default with a NULL and every age calculation on the
        # platform reads an unparseable entry_at as 0 days.
        if entry_at:
            _row["entry_at"] = entry_at
        return client.table("paper_positions").insert(_row).execute()

    try:
        ins = await asyncio.to_thread(_sync_insert)
        pos_id = (ins.data or [{}])[0].get("id") if ins.data else None
        return FillResult(ok=True, position_id=pos_id, fill_price=entry_price)
    except Exception as e:  # noqa: BLE001
        return FillResult(ok=False, error=str(e))


async def count_profit_steps(user_id: str, position_id: str) -> Optional[int]:
    """Count completed order identities, not cumulative partial-fill polls.

    Legacy outcomes without a broker order ID retain their per-row identity.
    An incomplete/failed read is unknown, never a fresh zero-step ladder.
    """
    client = _supabase()
    if not client:
        return None

    def _q():
        identities = set()
        page_size = 500
        for offset in range(0, 50000, page_size):
            response = (client.table("trade_outcomes")
                        .select("id,entry_payload")
                        .eq("user_id", user_id).eq("position_id", position_id)
                        .eq("exit_reason", "profit_step").order("id")
                        .range(offset, offset + page_size - 1).execute())
            rows = response.data
            if not isinstance(rows, list):
                return None
            for row in rows:
                order_id = _payload_dict(_payload_dict(row.get("entry_payload")).get("broker_accounting")).get("exit_order_id")
                if order_id:
                    identities.add(("order", str(order_id)))
                elif row.get("id"):
                    identities.add(("legacy", str(row["id"])))
                else:
                    return None
            if len(rows) < page_size:
                return len(identities)
        return None
    try:
        return await asyncio.to_thread(_q)
    except Exception:  # noqa: BLE001
        return None


from app.paper.position_status import assert_valid as _assert_status

# Validated at import: if someone edits this to a status the schema does
# not allow, the agents refuse to start instead of silently failing to
# book every partial from then on.
_POS_PARTIAL = _assert_status("closed_partial", "record_external_partial_close")


def _validated_broker_receipt(receipt: dict) -> dict:
    """Keep only a confirmed cumulative order receipt, never a quote/model.

    `fee_usd` means a known cumulative cash fee for THIS closing order. Absence
    is unknown, not a free trade. Entry-cost provenance is checked in the RPC.
    """
    from decimal import Decimal, InvalidOperation
    if not isinstance(receipt, dict):
        raise ValueError("Broker order receipt required")
    out = {key: receipt.get(key) for key in (
        "id", "symbol", "side", "status", "filled_qty", "filled_avg_price", "filled_at")}
    if (not isinstance(out["id"], str) or not out["id"].strip()
            or not isinstance(out["symbol"], str) or not out["symbol"].strip()
            or out["side"] not in ("buy", "sell")
            or out["status"] not in ("filled", "partially_filled", "canceled", "expired", "rejected", "done_for_day")):
        raise ValueError("Broker receipt is incomplete or unfilled")
    for key in ("filled_qty", "filled_avg_price", "fee_usd"):
        val = receipt.get(key)
        if key == "fee_usd" and val is None:
            continue
        try:
            num = Decimal(str(val))
        except (InvalidOperation, TypeError, ValueError):
            raise ValueError("Broker receipt has invalid numeric evidence") from None
        if not num.is_finite() or (num < 0 if key == "fee_usd" else num <= 0):
            raise ValueError("Broker receipt has invalid numeric evidence")
        if key == "filled_qty":
            try:
                if num >= Decimal("1e18") or num != num.quantize(Decimal("0.000000000001")):
                    raise ValueError("Broker receipt quantity exceeds ledger precision")
            except InvalidOperation:
                raise ValueError("Broker receipt quantity exceeds ledger precision") from None
        out[key] = str(num)
    try:
        stamp = datetime.fromisoformat(str(out["filled_at"]).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError("Broker receipt requires a timezone-aware fill timestamp") from None
    out["filled_at"] = stamp.astimezone(timezone.utc).isoformat()
    return out


async def record_broker_close(
    user_id: str, position_id: str, receipt: dict, reason: str = "manual",
) -> FillResult:
    """Atomically book only new confirmed fills; duplicate orders are harmless.

    Requires the broker_close_receipts migration to be installed first.
    Missing RPC, rejected evidence or DB failure leaves every ledger row intact.
    The transaction owns outcome/counter writes; never repeat them in Python.
    Cash stays broker-snapshot sourced, avoiding a second credit after a sync.
    """
    try:
        evidence = _validated_broker_receipt(receipt)
    except ValueError as exc:
        return FillResult(ok=False, position_id=position_id, pending=True, error=str(exc))
    client = _supabase()
    if not client:
        return FillResult(ok=False, pending=True, error="Supabase not configured")
    try:
        result = await asyncio.to_thread(lambda: client.rpc("record_broker_close", {
            "p_user_id": str(user_id), "p_position_id": str(position_id),
            "p_receipt": evidence, "p_reason": str(reason),
        }).execute())
        data = getattr(result, "data", None)
        if not isinstance(data, dict) or data.get("ok") is not True:
            return FillResult(ok=False, position_id=position_id, pending=True,
                              error="Atomic broker fill accounting returned no confirmation")
        return FillResult(
            ok=True, position_id=position_id, broker_order_id=evidence["id"],
            fill_price=float(data.get("fill_price") or 0),
            realized_pnl_usd=float(data.get("realized_pnl_usd") or 0),
            duplicate=bool(data.get("duplicate")), pending=bool(data.get("pending")),
            remaining_qty=float(data.get("remaining_qty") or 0),
            fees_complete=bool(data.get("fees_complete")),
            pnl_provisional=bool(data.get("pnl_provisional", True)),
        )
    except Exception:  # No sequential-write fallback; no credential-bearing error text.
        return FillResult(ok=False, position_id=position_id, pending=True,
                          error="Atomic broker fill accounting unavailable or receipt rejected; "
                                "verify schema installation and reconcile the pending order")


async def record_external_partial_close(
    user_id: str, position_id: str, slice_qty: float, fill_price: float,
    reason: str = "profit_step", *, receipt: Optional[dict] = None,
) -> FillResult:
    """Compatibility boundary: a caller-supplied slice/price is not evidence."""
    if receipt is None:
        return FillResult(ok=False, position_id=position_id, pending=True,
                          error="Confirmed broker order receipt required for external partial close")
    return await record_broker_close(user_id, position_id, receipt, reason)


async def record_external_close(
    user_id: str, position_id: str, exit_price: float,
    reason: str = "alpaca_bracket", *, receipt: Optional[dict] = None,
) -> FillResult:
    """Quote-only reconciliation must leave the position pending verification."""
    if receipt is None:
        return FillResult(ok=False, position_id=position_id, pending=True,
                          error="Confirmed broker order receipt required for external close")
    return await record_broker_close(user_id, position_id, receipt, reason)


async def trim_position(
    user_id: str,
    position_id: str,
    fraction: float = 0.5,
    price: float = 0.0,
    reason: str = "trim",
) -> FillResult:
    """Sell a fraction of an open INTERNAL paper position, leaving the
    remainder open (the "runner"). Implemented 2026-06-11 -- the Exit
    Advisor's warn-tier auto-trim (Task #92) imported this function but
    it did not exist, and because it shared an import statement with
    close_position_broker_aware inside a try/except-pass, the missing
    name silently disabled the ENTIRE auto-exit path, urgent closes
    included.

    Mirrors close_position() economics on the trimmed slice: slippage,
    commission, realized P&L into account today/ytd/week totals, and
    proceeds back to cash. The row stays status="open" with reduced
    quantity; the trim is recorded in the notes column (the
    realized_pnl_usd column is only written at final close, which
    covers the remaining quantity -- account totals carry the trim).

    Internal-paper rows ONLY. Alpaca-routed rows need the bracket
    cancel -> partial sell -> re-submit pattern (deferred); callers
    already gate on broker != "alpaca".
    """
    client = _supabase()
    if not client:
        return FillResult(ok=False, error="Supabase not configured")
    try:
        fraction = float(fraction)
    except (TypeError, ValueError):
        return FillResult(ok=False, error="Bad fraction")
    if not (0.0 < fraction < 1.0):
        return FillResult(ok=False, error="Fraction must be between 0 and 1")

    def _sync_get():
        return (
            client.table("paper_positions")
            .select("*")
            .eq("id", position_id)
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )

    res = await asyncio.to_thread(_sync_get)
    pos = res.data if res else None
    if not pos or pos.get("status") != "open":
        return FillResult(ok=False, error="Position not open")
    if (pos.get("broker") or "").lower().strip() == "alpaca":
        # Defense in depth -- callers gate this too.
        return FillResult(ok=False, error="Trim on Alpaca-routed rows not supported yet")

    side = pos["side"]
    qty = float(pos["quantity"])
    entry = float(pos["entry_price"])
    asset_type = pos["asset_type"]
    trim_qty = qty * fraction
    remain_qty = qty - trim_qty
    if trim_qty <= 0 or remain_qty <= 0:
        return FillResult(ok=False, error="Trim quantity rounds to zero")

    fill_price = apply_slippage(price, side, "close")
    notional = trim_qty * fill_price
    fee = commission(asset_type, notional)
    if side == "long":
        gross_pnl = trim_qty * (fill_price - entry)
    else:
        gross_pnl = trim_qty * (entry - fill_price)
    pnl = gross_pnl - fee

    # paper_positions has NO notes column (verified 2026-06-11) --
    # record the trim inside the source_payload jsonb instead.
    sp = pos.get("source_payload")
    sp = dict(sp) if isinstance(sp, dict) else {}
    trims = list(sp.get("trims") or [])
    trims.append({
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sold_qty": trim_qty,
        "of_qty": qty,
        "fill_price": fill_price,
        "realized_pnl_usd": round(pnl, 4),
        "reason": reason,
    })
    sp["trims"] = trims

    def _sync_trim():
        return (
            client.table("paper_positions")
            .update({
                "quantity": remain_qty,
                "fees_usd": float(pos.get("fees_usd", 0)) + fee,
                "source_payload": sp,
            })
            .eq("id", position_id)
            .execute()
        )

    await asyncio.to_thread(_sync_trim)

    account = await get_account(user_id)
    if account:
        new_cash = float(account["current_cash_usd"]) + notional - fee
        new_today = float(account["today_realized_pnl_usd"]) + pnl
        new_ytd = float(account["ytd_realized_pnl_usd"]) + pnl
        new_week = float(account.get("week_realized_pnl_usd") or 0) + pnl

        def _sync_update_account():
            return (
                client.table("paper_accounts")
                .update({
                    "current_cash_usd": new_cash,
                    "today_realized_pnl_usd": new_today,
                    "ytd_realized_pnl_usd": new_ytd,
                    "week_realized_pnl_usd": new_week,
                })
                .eq("user_id", user_id)
                .execute()
            )

        await asyncio.to_thread(_sync_update_account)

    return FillResult(ok=True, fill_price=fill_price, realized_pnl_usd=pnl)


async def close_position_broker_aware(
    user_id: str, position_id: str, market_price: float, reason: str = "manual",
) -> FillResult:
    """Internal rows simulate; broker rows use bound, durable receipt settlement."""
    client = _supabase()
    if not client:
        return FillResult(ok=False, error="Supabase not configured")
    try:
        res = await asyncio.to_thread(lambda: client.table("paper_positions")
            .select("*").eq("id", position_id).eq("user_id", user_id)
            .maybe_single().execute())
        pos = res.data if res else None
    except Exception:
        return FillResult(ok=False, pending=True, error="Position lookup unavailable")
    if not pos or pos.get("status") != "open":
        return FillResult(ok=False, error="Position not open")
    if str(pos.get("broker") or "").strip().lower() == "alpaca":
        from app.brokers.accounts import bind_for_user
        from app.brokers.route_guard import check_route
        from app.paper.broker_exit import settle_or_request_close
        try:
            with bind_for_user(str(user_id)) as account:
                if account is None or not check_route(str(user_id))[0]:
                    return FillResult(ok=False, pending=True, error="Unresolved broker book")
                return await settle_or_request_close(pos, reason)
        except Exception:
            return FillResult(ok=False, pending=True, error="Broker exit remains unverified")
    return await close_position(user_id, position_id, market_price, reason=reason)
