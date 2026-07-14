"""Re-arm Alpaca exit legs after an engine-side risk adjustment.

Mike 2026-07-14 (the RBLX morning): the reevaluator tightened stops and
lowered targets in the BOOKS, but for broker-held stocks the stale legs
kept sitting at Alpaca -- the far-away $59.81 sell never moved while the
price reversed away from it. Every engine-side adjustment to a broker
position must now CANCEL the old legs and re-arm an OCO at the new
prices, using the same verified cancel-first dance as the profit-step.
Long stocks only (v1); crypto has no broker legs (monitor owns those
exits internally).
"""

from __future__ import annotations

import asyncio


async def resync_alpaca_legs(row: dict, new_stop=None, new_target=None,
                             why: str = "") -> tuple[bool, str]:
    """Cancel open orders for the row's symbol and re-arm an OCO at the
    row's CURRENT stop/target (or the overrides). Never raises; returns
    (ok, note). Fail-open: on any failure the caller's DB state still
    stands and the next monitor pass / manual action can retry."""
    try:
        from app.brokers.alpaca import (
            alpaca_configured, cancel_open_orders_for, get_open_orders_for,
            submit_oco_sell,
        )
        sym = str(row.get("ticker") or "").upper()
        if (str(row.get("broker") or "") != "alpaca"
                or str(row.get("asset_type") or "stock") != "stock"):
            return False, "not an alpaca stock row"
        if str(row.get("side") or "long").lower() != "long":
            return False, "long-only v1"
        qty = float(row.get("quantity") or 0)
        stop_p = float(new_stop if new_stop is not None
                       else (row.get("stop_price") or 0))
        tgt_p = float(new_target if new_target is not None
                      else (row.get("target_price") or 0))
        if not (alpaca_configured() and sym and qty > 0
                and stop_p > 0 and tgt_p > stop_p):
            return False, "bad inputs"
        _n, err = await cancel_open_orders_for(sym)
        if err:
            return False, f"cancel failed: {err}"
        for _ in range(6):
            left = await get_open_orders_for(sym)
            if not left:
                break
            await asyncio.sleep(0.7)
        o, oerr = await submit_oco_sell(sym, qty, limit_price=round(tgt_p, 2),
                                        stop_price=round(stop_p, 2))
        if oerr or not o:
            return False, f"OCO re-arm failed: {oerr}"
        try:
            from app.agents.activity_log import record as _rec
            _rec("legs_resynced", sym,
                 reason=(f"broker exit legs re-armed: target {tgt_p:.2f}, "
                         f"stop {stop_p:.2f}"
                         + (f" -- {why}" if why else "")),
                 extra={"user_id": str(row.get("user_id") or "")})
        except Exception:  # noqa: BLE001
            pass
        return True, "ok"
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:120]
