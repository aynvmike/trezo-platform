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
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from app.config import get_settings


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


# ---- Helpers --------------------------------------------------------------


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
    plan = plan_position(
        equity=equity,
        entry_price=fill_price,
        stop_price=stop_price,
        target_price=target_price,
        risk_pct=risk_pct,
        asset_type=asset_type,
        buying_power=(min(cash, max_notional) if max_notional is not None else cash),
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
) -> FillResult:
    """Insert a tracking row for a position executed on an external broker
    (e.g. Alpaca). No cash math here - the broker holds the real account;
    this row exists so Trezo's dashboard and monitor can see the position."""
    client = _supabase()
    if not client:
        return FillResult(ok=False, error="Supabase not configured")

    def _sync_insert():
        return (
            client.table("paper_positions")
            .insert({
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
            })
            .execute()
        )

    try:
        ins = await asyncio.to_thread(_sync_insert)
        pos_id = (ins.data or [{}])[0].get("id") if ins.data else None
        return FillResult(ok=True, position_id=pos_id, fill_price=entry_price)
    except Exception as e:  # noqa: BLE001
        return FillResult(ok=False, error=str(e))


async def record_external_partial_close(
    user_id: str,
    position_id: str,
    slice_qty: float,
    fill_price: float,
    reason: str = "profit_step",
) -> FillResult:
    """Book a PARTIAL close of an external-broker (Alpaca) position:
    a closed-slice row is written (so the row-truth kill-switch and the
    learning loop both see the banked P/L) and the open row's quantity is
    reduced. No cash/counter mutation -- external rows follow
    record_external_close's convention: rows are the truth (2026-07-02)."""
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
    qty_total = float(pos.get("quantity") or 0)
    sq = float(slice_qty)
    if sq <= 0 or sq >= qty_total:
        return FillResult(ok=False, error="Bad slice quantity")
    entry = float(pos.get("entry_price") or 0)
    side = pos.get("side") or "long"
    pnl = (sq * (fill_price - entry) if side == "long"
           else sq * (entry - fill_price))
    now_iso = datetime.now(timezone.utc).isoformat()

    def _ins_slice():
        return client.table("paper_positions").insert({
            "user_id": user_id,
            "ticker": pos.get("ticker"),
            "asset_type": pos.get("asset_type"),
            "side": side,
            "broker": pos.get("broker"),
            "strategy": pos.get("strategy"),
            "quantity": sq,
            "entry_price": entry,
            "entry_at": pos.get("entry_at"),
            "stop_price": pos.get("stop_price"),
            "target_price": pos.get("target_price"),
            "source_payload": pos.get("source_payload"),
            "fees_usd": 0,
            "status": "closed_partial",
            "exit_price": fill_price,
            "exit_at": now_iso,
            "realized_pnl_usd": round(pnl, 2),
        }).execute()

    def _shrink():
        return (client.table("paper_positions")
                .update({"quantity": qty_total - sq})
                .eq("id", position_id).execute())

    try:
        await asyncio.to_thread(_ins_slice)
        await asyncio.to_thread(_shrink)
        try:
            from app.learning.outcomes import record_paper_close
            await record_paper_close(
                user_id=user_id,
                position_id=position_id,
                ticker=pos.get("ticker"),
                asset_type=pos.get("asset_type"),
                side=side,
                strategy=pos.get("strategy"),
                direction=(pos.get("source_payload") or {}).get("direction"),
                entry_price=entry,
                exit_price=fill_price,
                quantity=sq,
                realized_pnl_usd=pnl,
                exit_reason=reason,
                status="closed_partial",
                opened_at=pos.get("entry_at"),
                closed_at=now_iso,
                source_payload=pos.get("source_payload"),
            )
        except Exception:  # noqa: BLE001
            pass
        return FillResult(ok=True, position_id=position_id,
                          fill_price=fill_price,
                          realized_pnl_usd=round(pnl, 2))
    except Exception as e:  # noqa: BLE001
        return FillResult(ok=False, error=str(e))


async def record_external_close(
    user_id: str,
    position_id: str,
    exit_price: float,
    reason: str = "alpaca_bracket",
) -> FillResult:
    """Mark an external-broker tracking position closed."""
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

    qty = float(pos.get("quantity") or 0)
    entry = float(pos.get("entry_price") or 0)
    side = pos.get("side")
    tgt = float(pos.get("target_price") or 0)
    stp = float(pos.get("stop_price") or 0)

    if side == "long":
        pnl = qty * (exit_price - entry)
        status = ("closed_target" if (tgt and exit_price >= tgt)
                  else "closed_stop" if (stp and exit_price <= stp)
                  else "closed_manual")
    else:
        pnl = qty * (entry - exit_price)
        status = ("closed_target" if (tgt and exit_price <= tgt)
                  else "closed_stop" if (stp and exit_price >= stp)
                  else "closed_manual")

    def _sync_close():
        return (
            client.table("paper_positions")
            .update({
                "status": status,
                "exit_price": exit_price,
                "exit_at": datetime.now(timezone.utc).isoformat(),
                "realized_pnl_usd": round(pnl, 2),
            })
            .eq("id", position_id)
            .execute()
        )

    try:
        await asyncio.to_thread(_sync_close)

        # Phase 13/14 - learning-loop recorder.
        try:
            from app.learning.outcomes import record_paper_close
            await record_paper_close(
                user_id=user_id,
                position_id=position_id,
                ticker=pos.get("ticker"),
                asset_type=pos.get("asset_type"),
                side=side,
                strategy=pos.get("strategy"),
                direction=(pos.get("source_payload") or {}).get("direction"),
                entry_price=entry,
                exit_price=exit_price,
                quantity=qty,
                realized_pnl_usd=pnl,
                exit_reason=reason,
                status=status,
                opened_at=pos.get("entry_at"),
                closed_at=datetime.now(timezone.utc).isoformat(),
                source_payload=pos.get("source_payload"),
            )
        except Exception:  # noqa: BLE001
            pass

        return FillResult(
            ok=True, position_id=position_id,
            fill_price=exit_price, realized_pnl_usd=pnl,
        )
    except Exception as e:  # noqa: BLE001
        return FillResult(ok=False, error=str(e))



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
    user_id: str,
    position_id: str,
    market_price: float,
    reason: str = "manual",
) -> FillResult:
    """Broker-aware wrapper around close_position().

    For rows where broker == "alpaca", first calls Alpaca's
    DELETE /v2/positions/{ticker} (liquidate_position) which
    automatically cancels any open bracket legs and submits a market
    close at Alpaca. Only after Alpaca returns success do we update the
    Trezo row via close_position(). On Alpaca failure the Trezo row
    stays open so the next reconcile tick can retry; we DO NOT
    optimistically close the Trezo row and leave Alpaca holding the bag
    (that was the Gap 2 bug from 2026-06-11).

    For non-Alpaca rows, falls through to plain close_position().
    """
    import structlog
    _log = structlog.get_logger("trezo.engine")
    client = _supabase()
    if not client:
        return FillResult(ok=False, error="Supabase not configured")

    # Read the row to find out broker + ticker
    def _sync_get():
        return (
            client.table("paper_positions")
            .select("ticker, broker, status, asset_type")
            .eq("id", position_id)
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
    res = await asyncio.to_thread(_sync_get)
    pos = res.data if res else None
    if not pos:
        return FillResult(ok=False, error="Position not found")
    if pos.get("status") != "open":
        return FillResult(ok=False, error="Position not open")

    broker = (pos.get("broker") or "").lower().strip()
    ticker = (pos.get("ticker") or "").upper().strip()
    # Task #10 (2026-06-11): pass asset_type so crypto liquidations hit
    # Alpaca with the pair symbol ('BTCUSD'), not the bare ticker ('BTC')
    # which 404s and would leave the row stuck open forever.
    a_type = (pos.get("asset_type") or "stock").lower().strip()

    if broker == "alpaca" and ticker:
        # 1) Liquidate at Alpaca (cancels bracket legs + closes the position).
        try:
            from app.brokers.alpaca import liquidate_position
            liq, liq_err = await liquidate_position(ticker, asset_type=a_type)
            if liq_err:
                _log.warning(
                    "engine.broker_aware_close.alpaca_liquidate_failed",
                    ticker=ticker, position_id=position_id, error=liq_err,
                )
                # Leave the Trezo row open - next Position Monitor tick will
                # reconcile naturally if Alpaca did actually close.
                return FillResult(
                    ok=False,
                    error=f"alpaca liquidate failed: {liq_err}",
                )
            _log.info(
                "engine.broker_aware_close.alpaca_liquidate_ok",
                ticker=ticker, position_id=position_id, reason=reason,
            )
        except Exception as e:  # noqa: BLE001
            _log.warning(
                "engine.broker_aware_close.alpaca_liquidate_raised",
                ticker=ticker, position_id=position_id, error=str(e)[:200],
            )
            return FillResult(
                ok=False,
                error=f"alpaca liquidate raised: {str(e)[:200]}",
            )

    # 2) Mark the Trezo row closed (always, whether Alpaca-routed or not).
    return await close_position(user_id, position_id, market_price, reason=reason)
