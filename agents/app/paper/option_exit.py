"""Durable option close intents and atomic accounting from broker receipts."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import math
import uuid


def _result(error, pending=False):
    from app.paper.engine import FillResult
    return FillResult(ok=False, error=error, pending=pending)


async def _rpc(client, name, args):
    reply = await asyncio.to_thread(lambda: client.rpc(name, args).execute())
    body = reply.data if reply is not None else None
    if isinstance(body, list) and len(body) == 1:
        body = body[0]
    return body if isinstance(body, dict) else {}


async def _claim(client, row, expected, pending):
    try:
        body = await _rpc(client, "claim_option_broker_exit", {
            "p_user_id": str(row["user_id"]), "p_position_id": str(row["id"]),
            "p_expected_pending": expected, "p_pending": pending,
        })
        if body.get("ok") is True and body.get("claimed") is True:
            row["broker_exit_pending"] = pending
            return True
    except Exception:
        pass
    return False


def _matching_receipt(order, intent):
    try:
        if (not isinstance(order, dict) or str(order.get("id")) != str(intent["order_id"])
                or order.get("symbol") != intent["symbol"] or order.get("side") != intent["side"]):
            return False
        qty = float(order.get("filled_qty") or 0)
        requested = float(intent["quantity"])
        if not math.isfinite(qty) or qty < 0 or qty > requested:
            return False
        stamp = order.get("filled_at") or order.get("submitted_at") or order.get("created_at")
        at = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        started = datetime.fromisoformat(str(intent["started_at"]).replace("Z", "+00:00"))
        return at.tzinfo is not None and started.tzinfo is not None and at >= started
    except (ValueError, TypeError, KeyError, OverflowError):
        return False


async def _settle(client, row, intent, order):
    if not _matching_receipt(order, intent):
        return _result("option exit receipt identity, time or quantity mismatch", True)
    qty = float(order.get("filled_qty") or 0)
    if qty > 0:
        return await record_option_receipt(client, row, order, str(intent.get("reason") or "harvest"))
    if order.get("status") in ("canceled", "cancelled", "rejected", "expired"):
        await _claim(client, row, intent, None)
        return _result("option close ended with no confirmed fill")
    return _result("option exit awaiting confirmed fill", True)


async def record_option_receipt(client, row, order, reason="reconciled"):
    """Every options ledger close crosses the same atomic receipt boundary."""
    try:
        from app.paper.engine import _validated_broker_receipt, FillResult
        receipt = _validated_broker_receipt(order)
        body = await _rpc(client, "record_option_broker_close", {
            "p_user_id": str(row["user_id"]), "p_position_id": str(row["id"]),
            "p_receipt": receipt, "p_reason": reason,
        })
        if body.get("ok") is True:
            return FillResult(ok=True, position_id=str(row["id"]),
                              fill_price=float(body.get("fill_price") or 0),
                              realized_pnl_usd=float(body.get("realized_pnl_usd") or 0),
                              pending=bool(body.get("pending")),
                              duplicate=bool(body.get("duplicate")),
                              remaining_qty=float(body.get("remaining_qty") or 0),
                              fees_complete=bool(body.get("fees_complete", False)),
                              pnl_provisional=bool(body.get("pnl_provisional", True)),
                              broker_order_id=str(receipt["id"]))
    except Exception:
        pass
    return _result("atomic option fill accounting unavailable; receipt remains pending", True)


async def settle_or_request_option_close(client, row, *, symbol=None, side=None,
                                         quantity=None, limit_price=None,
                                         reason="harvest", token=None):
    """Poll a known pending order, or claim a new close before submission.

    Missing RPCs, failed reads and lost submission responses preserve unknown
    state. None of those events modifies position quantity or profit.
    """
    from app.brokers.accounts import bind_for_user, should_skip_unresolved
    from app.brokers.route_guard import check_route
    from app.brokers.alpaca import get_order_strict, get_option_positions_strict, submit_option_order
    from app.paper.broker_exit import _bound_book_verified
    uid = str(row.get("user_id") or "")
    if not uid or not row.get("id") or should_skip_unresolved(uid):
        return _result("option exit book identity unavailable")
    with bind_for_user(uid) as account:
        try:
            if not _bound_book_verified(uid, account):
                return _result("option exit paper book transport unverified")
            okay, _ = check_route(uid)
            if not okay:
                return _result("option exit route unverified")
            intent = row.get("broker_exit_pending")
            if intent is not None:
                if not isinstance(intent, dict) or not intent.get("order_id"):
                    return _result("option exit submission outcome unknown; no resubmission", True)
                order, error = await get_order_strict(str(intent["order_id"]), token=token)
                if error or not isinstance(order, dict):
                    return _result("pending option close receipt unavailable", True)
                return await _settle(client, row, intent, order)
            qty = float(quantity)
            price = float(limit_price)
            if (side not in ("buy", "sell") or not symbol or not math.isfinite(qty)
                    or qty <= 0 or not qty.is_integer() or qty > float(row.get("contracts") or 0)
                    or not math.isfinite(price) or price <= 0):
                return _result("option close request invalid")
            positions = await get_option_positions_strict(token=token)
            matches = [p for p in positions or [] if isinstance(p, dict) and p.get("symbol") == symbol]
            if positions is None or len(matches) != 1:
                return _result("option broker holding unavailable; close not submitted")
            held = float(matches[0].get("qty") or 0)
            if (not math.isfinite(held) or abs(held) != float(row.get("contracts") or 0)
                    or (side == "buy" and held >= 0) or (side == "sell" and held <= 0)):
                return _result("option broker quantity or direction differs from ledger; close not submitted")
            intent = {"intent_id": uuid.uuid4().hex,
                      "started_at": datetime.now(timezone.utc).isoformat(),
                      "reason": reason, "quantity": int(qty), "symbol": symbol,
                      "side": side, "order_id": None}
            if not await _claim(client, row, None, intent):
                return _result("option exit intent not claimed; submission blocked", True)
            order, error = await submit_option_order(
                symbol, int(qty), side, time_in_force="day", limit_price=price, token=token)
            if error or not isinstance(order, dict) or not order.get("id"):
                return _result("option exit submission unknown; no resubmission", True)
            linked = {**intent, "order_id": str(order["id"])}
            if not await _claim(client, row, intent, linked):
                return _result("option exit accepted but order link failed; inspect broker", True)
            return await _settle(client, row, linked, order)
        except Exception:
            return _result("option exit unresolved; no quantity or P&L assumed", True)
