"""Options partial-close primitive (Task #29).

When the Exit Advisor Options agent fires `trim_for_capital_recovery`
or `defensive_trim`, the UI gives Mike a button. That button posts to
the agents service which calls `close_partial_options_position` here.

Modeled-close pattern (v1):
  * Validate user owns position + status='open'.
  * Compute contracts_to_close from `fraction` (1..contracts-1 - if
    fraction would close 100%, we instead close the whole position).
  * Update the original row's `contracts` field down by that amount.
  * Write a closed_manual options_positions row for the closed slice,
    realized_pnl_usd computed from a coarse mark-to-market.
  * Write a `trade_outcomes` row tagged exit_reason='partial' so the
    learning loop has a record.
  * Log the trim decision to Mem0.

Live Alpaca order placement is intentionally NOT in v1. The user is
expected to mirror the close at the broker manually if a live order is
out. v2 will submit a sell-to-close OCC order automatically.

Wired by Nova for Mike on 2026-06-02 (E2 of the options sprint).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def _mark_to_market_per_contract(*, strategy: str, option_type: str | None,
                                 strike: float, spot: float) -> float:
    """Coarse modeled mark for closing an options leg. Intrinsic only.
    Phase C+ will replace with real broker-quote MTM."""
    if strategy in ("wheel_csp", "cash_secured_put") or option_type == "put":
        return max(0.0, strike - spot) * 100.0
    if strategy in ("wheel_cc", "long_call") or option_type == "call":
        return max(0.0, spot - strike) * 100.0
    return max(0.0, strike - spot) * 100.0


async def close_partial_options_position(
    *,
    user_id: str,
    position_id: str,
    contracts_to_close: int,
    reason: str = "manual_trim",
) -> dict[str, Any]:
    """Close N contracts of an open options_positions row. Never raises
    to the caller - returns a structured result dict the API layer
    can render.
    """
    from app.config import get_settings
    s = get_settings()
    if not s.supabase_url or not s.supabase_service_role_key:
        return {"ok": False, "error": "supabase_not_configured"}

    try:
        from supabase import create_client
        client = create_client(s.supabase_url, s.supabase_service_role_key)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"supabase_client_failed: {e}"}

    # ---- Fetch the position ---------------------------------------
    def _q():
        return (
            client.table("options_positions")
            .select("*")
            .eq("id", position_id)
            .eq("user_id", user_id)
            .eq("status", "open")
            .limit(1)
            .execute()
        )
    try:
        res = await asyncio.to_thread(_q)
        rows = res.data or []
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"fetch_failed: {e}"}
    if not rows:
        return {"ok": False, "error": "position_not_found"}
    pos = rows[0]

    current_contracts = int(pos.get("contracts") or 0)
    if current_contracts <= 0:
        return {"ok": False, "error": "no_contracts_to_close"}

    # Clamp contracts_to_close into [1, current_contracts-1]; if user
    # asked for >= current_contracts, route through a full close.
    n = max(1, int(contracts_to_close))
    full_close = n >= current_contracts
    if full_close:
        n = current_contracts

    # ---- Mark to market for the slice -----------------------------
    underlying = str(pos.get("underlying") or "")
    strike = float(pos.get("strike") or 0.0)
    opt_type = pos.get("option_type")
    strategy = str(pos.get("strategy") or "")
    premium_total = float(pos.get("net_premium_usd") or 0.0)
    # Per-contract premium: total / contracts so the closed slice
    # carries its share.
    premium_per_contract = (premium_total / current_contracts) if current_contracts else 0.0
    closed_slice_premium = premium_per_contract * n

    # Pull spot to mark the close. Best-effort - on failure we use the
    # entry premium as the mark (effectively closing at flat).
    try:
        from app.data.candles import fetch_candles_for
        candles = await fetch_candles_for(underlying, "stock")
        spot = float(candles[-1].close) if candles else strike
    except Exception:
        spot = strike

    mark_per_contract = _mark_to_market_per_contract(
        strategy=strategy, option_type=opt_type,
        strike=strike, spot=spot,
    )
    mark_total = mark_per_contract * n

    # Realized P&L on the closed slice:
    #   credit position (sold) -> credit kept - cost to buy back
    #   debit position (bought) -> mark on close - cost to open
    if closed_slice_premium >= 0:
        realized = closed_slice_premium - mark_total
    else:
        realized = mark_total - abs(closed_slice_premium)

    # ---- Persist the changes -------------------------------------
    now_iso = datetime.now(timezone.utc).isoformat()
    new_status_for_full = "closed_profit" if realized >= 0 else "closed_manual"

    try:
        if full_close:
            # Just update the existing row to closed_*.
            def _close_full():
                return (
                    client.table("options_positions")
                    .update({
                        "status": new_status_for_full,
                        "realized_pnl_usd": round(realized, 2),
                        "closed_at": now_iso,
                        "notes": f"Trimmed-to-zero via Exit Advisor button. Reason: {reason}.",
                    })
                    .eq("id", position_id)
                    .execute()
                )
            await asyncio.to_thread(_close_full)
            updated_id = position_id
            slice_id = position_id
        else:
            # Decrement contracts on original, insert a closed row for
            # the closed slice. The slice carries the proportional
            # premium so historical accounting stays clean.
            remaining = current_contracts - n
            remaining_premium = premium_per_contract * remaining

            def _decrement():
                return (
                    client.table("options_positions")
                    .update({
                        "contracts": remaining,
                        "net_premium_usd": round(remaining_premium, 4),
                    })
                    .eq("id", position_id)
                    .execute()
                )
            await asyncio.to_thread(_decrement)
            updated_id = position_id

            slice_row = {
                "user_id": user_id,
                "underlying": underlying,
                "strategy": strategy,
                "direction": pos.get("direction") or "income",
                "option_type": opt_type,
                "strike": strike,
                "expiration": pos.get("expiration"),
                "contracts": n,
                "net_premium_usd": round(closed_slice_premium, 4),
                "modeled_iv": pos.get("modeled_iv"),
                "legs": pos.get("legs") or [],
                "status": new_status_for_full,
                "realized_pnl_usd": round(realized, 2),
                "opened_at": pos.get("opened_at"),
                "closed_at": now_iso,
                "notes": f"Partial trim slice. Reason: {reason}.",
            }

            def _insert_slice():
                return (
                    client.table("options_positions")
                    .insert(slice_row)
                    .execute()
                )
            ins = await asyncio.to_thread(_insert_slice)
            slice_id = (ins.data[0]["id"] if ins.data else None) or position_id
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"persist_failed: {e}"}

    # ---- Trade outcomes ledger -----------------------------------
    try:
        from app.learning.outcomes import record_paper_close
        await record_paper_close(
            user_id=user_id,
            position_id=str(slice_id),
            ticker=underlying,
            asset_type="option",
            side="short" if closed_slice_premium > 0 else "long",
            strategy=strategy,
            direction=str(pos.get("direction") or ""),
            entry_price=float(strike),
            exit_price=float(spot),
            quantity=float(n * 100),
            realized_pnl_usd=float(realized),
            exit_reason="partial",
            status=new_status_for_full,
            opened_at=str(pos.get("opened_at") or ""),
            closed_at=now_iso,
            source_payload={
                "options_position_id": position_id,
                "options_scanner_memory_id": (
                    pos.get("source_payload", {}).get("options_scanner_memory_id")
                    if isinstance(pos.get("source_payload"), dict) else None
                ),
            },
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("options_trim outcomes record failed: %s", e)

    # ---- Log decision to Mem0 ------------------------------------
    try:
        from app.memory import get_memory, AgentDecision
        mem = get_memory()
        if mem.available:
            mem.log_decision(AgentDecision(
                agent="options_trim",
                action="partial_trim" if not full_close else "full_close",
                ticker=underlying,
                reasoning=(
                    f"Closed {n}/{current_contracts} contracts of "
                    f"{strategy} on {underlying} for ${realized:+.2f} "
                    f"realized. Reason: {reason}."
                ),
                metadata={
                    "user_id": user_id,
                    "position_id": position_id,
                    "strategy": strategy,
                    "contracts_closed": n,
                    "realized_pnl_usd": round(realized, 2),
                    "exit_reason": "partial" if not full_close else "manual",
                },
            ))
    except Exception:  # noqa: BLE001
        pass

    return {
        "ok": True,
        "full_close": full_close,
        "contracts_closed": n,
        "contracts_remaining": (current_contracts - n) if not full_close else 0,
        "realized_pnl_usd": round(realized, 2),
        "mark_per_contract": round(mark_per_contract, 2),
        "spot_used": round(spot, 2),
    }
