"""Stock-side reconciliation - extracted from main.py so PositionMonitor
can call it on its own schedule (Task #32, 2026-06-03 Mike's ask).

Why this exists: today /stocks/reconcile is a manual button. Options
already auto-reconciles every 30 min; stocks should too. Mike found a
phantom-position drift (Alpaca closed SOFI + INTC, Trezo still showed
them as open) that would have been caught automatically with a
30-minute background reconcile.

Returns the same shape the /stocks/reconcile endpoint used to return.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


async def reconcile_stocks_all_users() -> dict[str, Any]:
    """Reconcile every user's open paper_positions stocks against the
    Alpaca broker truth. Idempotent + safe to call from a tick loop.

    Mirrors the behavior of POST /stocks/reconcile exactly so both
    paths produce the same result.
    """
    from app.brokers.alpaca import (
        alpaca_configured, get_positions, UserToken,
    )
    from app.paper.engine import record_external_position
    from app.integrations.web_tokens import get_user_broker_token
    from app.config import get_settings

    s = get_settings()
    if not (s.supabase_url and s.supabase_service_role_key):
        return {"ok": False, "error": "Supabase not configured."}

    try:
        from supabase import create_client
        client = create_client(
            s.supabase_url, s.supabase_service_role_key
        )
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"Supabase client error: {e}"}

    if not alpaca_configured():
        return {"ok": False, "error": "Alpaca env keys not configured."}

    def _users():
        return client.table("paper_accounts").select("user_id").execute()
    user_rows = (await asyncio.to_thread(_users)).data or []

    total_updated = 0
    total_inserted = 0
    total_closed = 0
    per_user: list[dict] = []

    for u in user_rows:
        user_id = u.get("user_id")
        if not user_id:
            continue

        bt = await get_user_broker_token(user_id, "alpaca")
        token = UserToken(
            access_token=bt.access_token,
            refresh_token=bt.refresh_token,
            expires_at=bt.expires_at,
        ) if bt else None

        try:
            alpaca_positions = await get_positions(token=token)
        except Exception:
            alpaca_positions = []

        alpaca_by_sym: dict[str, dict] = {}
        for p in alpaca_positions:
            sym = str(p.get("symbol", "")).upper()
            if sym:
                alpaca_by_sym[sym] = p

        def _trezo_open(uid=user_id):
            return (
                client.table("paper_positions")
                .select(
                    "id, ticker, side, quantity, entry_price, "
                    "stop_price, target_price, strategy"
                )
                .eq("user_id", uid)
                .eq("status", "open")
                .eq("asset_type", "stock")
                .execute()
            )
        trezo_rows = (await asyncio.to_thread(_trezo_open)).data or []

        updated = 0
        closed = 0
        inserted = 0
        notes_list: list[str] = []

        # 1) Close or patch existing Trezo rows.
        for r in trezo_rows:
            sym = str(r["ticker"]).upper()
            ap = alpaca_by_sym.get(sym)
            if ap is None:
                # Trezo has it open; Alpaca does not. Close as manual
                # with a reconcile note.
                def _close(rid=r["id"]):
                    return (
                        client.table("paper_positions")
                        .update({
                            "status": "closed_manual",
                            "exit_price": None,
                            "realized_pnl_usd": 0,
                            "notes": (
                                "Auto-reconciled - not present at broker. "
                                "Phantom position closed by 30-min stocks "
                                "reconciliation tick."
                            ),
                        })
                        .eq("id", rid)
                        .execute()
                    )
                try:
                    await asyncio.to_thread(_close)
                    closed += 1
                    notes_list.append(f"{sym} closed (phantom)")
                except Exception:
                    continue
                continue

            # Both sides have it - check for qty / entry drift.
            try:
                ap_qty = abs(float(ap.get("qty") or 0))
                ap_entry = float(ap.get("avg_entry_price") or 0)
            except Exception:
                continue
            trezo_qty = float(r.get("quantity") or 0)
            trezo_entry = float(r.get("entry_price") or 0)

            if ap_qty <= 0:
                continue

            drift_qty = abs(ap_qty - trezo_qty) > 1e-6
            drift_entry = abs(ap_entry - trezo_entry) > 0.01
            if drift_qty or drift_entry:
                def _patch(rid=r["id"], q=ap_qty, e=ap_entry):
                    return (
                        client.table("paper_positions")
                        .update({"quantity": q, "entry_price": e})
                        .eq("id", rid)
                        .execute()
                    )
                try:
                    await asyncio.to_thread(_patch)
                    updated += 1
                    notes_list.append(
                        f"{sym} patched qty={ap_qty} entry={ap_entry}"
                    )
                except Exception:
                    pass

        # 2) Insert any Alpaca positions Trezo missed.
        trezo_syms = {str(r["ticker"]).upper() for r in trezo_rows}
        for sym, ap in alpaca_by_sym.items():
            if sym in trezo_syms:
                continue
            try:
                ap_qty = float(ap.get("qty") or 0)
                ap_entry = float(ap.get("avg_entry_price") or 0)
            except Exception:
                continue
            if abs(ap_qty) < 1e-6:
                continue
            side = "long" if ap_qty > 0 else "short"
            qty_abs = abs(ap_qty)

            # Best-effort stop/target from per-user defaults.
            try:
                from app.runtime.settings import get_bot_settings
                cfg = get_bot_settings(user_id)
                sp = float(cfg.default_stop_pct or 0.05)
                tp = float(cfg.default_target_pct or 0.10)
            except Exception:
                sp, tp = 0.05, 0.10
            if side == "long":
                stop_price = ap_entry * (1 - sp)
                target_price = ap_entry * (1 + tp)
            else:
                stop_price = ap_entry * (1 + sp)
                target_price = ap_entry * (1 - tp)

            try:
                await record_external_position(
                    user_id=str(user_id),
                    ticker=sym,
                    asset_type="stock",
                    side=side,
                    quantity=qty_abs,
                    entry_price=ap_entry,
                    stop_price=stop_price,
                    target_price=target_price,
                    strategy="reconciled",
                    broker="alpaca",
                    broker_order_id=None,
                    source_payload={
                        "auto_reconcile": True,
                        "alpaca_avg_entry": ap_entry,
                    },
                )
                inserted += 1
                notes_list.append(
                    f"{sym} inserted from broker (qty {qty_abs})"
                )
            except Exception:
                continue

        total_updated += updated
        total_inserted += inserted
        total_closed += closed
        per_user.append({
            "user_id": str(user_id),
            "updated": updated,
            "inserted": inserted,
            "closed": closed,
            "notes": notes_list,
        })

    return {
        "ok": True,
        "users_touched": len(per_user),
        "updated": total_updated,
        "inserted": total_inserted,
        "closed": total_closed,
        "details": per_user,
    }
