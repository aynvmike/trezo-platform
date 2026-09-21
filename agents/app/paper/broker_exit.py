"""Durable broker exit intent and receipt-only settlement.

The intent is claimed before an order can leave. Unknown submissions keep
the intent, so a timeout/restart cannot silently submit the same exit twice.
Only the atomic receipt recorder may reduce inventory or publish P/L.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import math
import uuid

PENDING_KEY = "broker_exit_pending"


def _result(*, error=None, pending=False):
    from app.paper.engine import FillResult
    return FillResult(ok=False, error=error, pending=pending)


def _stamp(value):
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return stamp if stamp.tzinfo is not None else None
    except (TypeError, ValueError):
        return None


def _symbol(value, at):
    from app.brokers.execution_price import _symbol as normalize
    return normalize(value, at)


def _bound_book_verified(uid, account):
    """Prove the transport uses the credentials of this exact paper book.

    The legacy route guard accepts single-account configurations; a dropped
    secondary registry entry must never thereby fall through to primary.
    """
    try:
        from app.brokers import alpaca
        from app.brokers.accounts import PAPER_BASE_URL
        return (account is not None and str(account.user_id) == str(uid)
                and alpaca.broker_venue() == "paper"
                and alpaca._base_url().rstrip("/") == PAPER_BASE_URL
                and alpaca._headers() == account.headers())
    except Exception:
        return False


async def _verify_exit_quantity(pos, requested, *, full_liquidation):
    """A symbol-wide liquidation may only dispose of this row's inventory."""
    from app.brokers.alpaca import get_positions_strict
    try:
        positions = await get_positions_strict()
        if positions is None:
            return False
        at = str(pos.get("asset_type") or "stock").lower()
        owned = [p for p in positions if isinstance(p, dict)
                 and _symbol(p.get("symbol"), at) == _symbol(pos.get("ticker"), at)]
        if len(owned) != 1:
            return False
        held = owned[0]
        qty, row_qty = abs(float(held["qty"])), float(pos["quantity"])
        if (str(held.get("side") or "").lower() != str(pos.get("side") or "").lower()
                or not all(math.isfinite(v) and v > 0 for v in (qty, row_qty, requested))):
            return False
        tolerance = max(1e-9, row_qty * 1e-8)
        if full_liquidation:
            return abs(qty - row_qty) <= tolerance and abs(requested - row_qty) <= tolerance
        return requested <= min(qty, row_qty) + tolerance
    except Exception:
        return False


def _matches(pos, order, *, since=None):
    if not isinstance(order, dict) or not order.get("id"):
        return False
    at = str(pos.get("asset_type") or "stock").lower()
    close_side = "sell" if pos.get("side") == "long" else "buy"
    if (_symbol(order.get("symbol"), at) != _symbol(pos.get("ticker"), at)
            or str(order.get("side") or "").lower() != close_side):
        return False
    earliest = _stamp(since or pos.get("entry_at"))
    # Native bracket legs can be CREATED alongside the entry before it
    # fills. Their closing execution time, not their creation time, binds
    # a completed receipt to this position's lifetime.
    created = (_stamp(order.get("filled_at"))
               or _stamp(order.get("submitted_at") or order.get("created_at")))
    # Matching by instrument alone could consume an earlier round trip.
    return earliest is not None and created is not None and created >= earliest


async def _claim(pos, expected, pending):
    from app.paper.engine import _supabase
    client = _supabase()
    if client is None:
        return False
    try:
        result = await asyncio.to_thread(lambda: client.rpc("claim_broker_exit", {
            "p_user_id": str(pos["user_id"]), "p_position_id": str(pos["id"]),
            "p_expected_pending": expected, "p_pending": pending,
        }).execute())
        body = result.data if result is not None else None
        if isinstance(body, list) and len(body) == 1:
            body = body[0]
        claimed = isinstance(body, dict) and body.get("ok") is True and body.get("claimed") is True
        if claimed:
            payload = dict(pos.get("source_payload") or {})
            if pending is None:
                payload.pop(PENDING_KEY, None)
            else:
                payload[PENDING_KEY] = dict(pending)
            pos["source_payload"] = payload
        return claimed
    except Exception:  # noqa: BLE001 -- missing RPC/read failure blocks submission
        return False


async def _read_order(order_id):
    from app.brokers.alpaca import get_order_strict
    return await get_order_strict(order_id)


async def _read_closing_orders(pos):
    """Find executions after entry, including earlier-created bracket legs."""
    from app.brokers.alpaca import get_fill_activities_strict
    activities = await get_fill_activities_strict(str(pos["entry_at"]), activity_types="FILL")
    if activities is None:
        return None
    at = str(pos.get("asset_type") or "stock").lower()
    close_side = "sell" if pos.get("side") == "long" else "buy"
    ids = set()
    for fill in activities:
        if (isinstance(fill, dict) and fill.get("order_id")
                and str(fill.get("side") or "").lower() == close_side
                and _symbol(fill.get("symbol"), at) == _symbol(pos.get("ticker"), at)):
            ids.add(str(fill["order_id"]))
    if len(ids) > 32:
        return None  # Bounded review, never a silently truncated evidence set.
    orders = []
    for oid in sorted(ids):
        order, error = await _read_order(oid)
        if error or order is None or str(order.get("id") or "") != oid:
            return None
        orders.append(order)
    return orders


async def _record(pos, order, reason):
    from app.paper.engine import record_broker_close
    return await record_broker_close(str(pos["user_id"]), str(pos["id"]), order, reason=reason)


def _note(pos, event, reason, **extra):
    try:
        from app.agents.activity_log import record
        record(event, str(pos.get("ticker") or "?"), reason=reason,
               extra={"user_id": str(pos.get("user_id") or ""),
                      "position_id": str(pos.get("id") or ""), **extra})
    except Exception:  # noqa: BLE001
        pass


async def _settle(pos, order, pending, reason):
    if not _matches(pos, order, since=pending.get("started_at") if isinstance(pending, dict) else None):
        return _result(error="broker exit receipt identity/time mismatch", pending=True)
    try:
        qty = float(order.get("filled_qty") or 0)
    except (TypeError, ValueError):
        qty = float("nan")
    status = str(order.get("status") or "").lower()
    if not math.isfinite(qty) or qty < 0:
        return _result(error="invalid broker exit quantity", pending=True)
    if isinstance(pending, dict):
        try:
            requested = float(pending["quantity"])
        except (KeyError, ValueError, TypeError):
            return _result(error="invalid broker exit intent quantity", pending=True)
        if (not math.isfinite(requested) or requested <= 0
                or qty > requested + max(1e-9, requested * 1e-8)):
            return _result(error="broker exit fill exceeds requested quantity", pending=True)
    if qty > 0:
        # The recorder validates price/time/quantity and deduplicates cumulative
        # receipts atomically. A failure leaves the durable order id intact.
        try:
            result = await _record(pos, order, reason)
        except Exception:
            return _result(error="broker receipt accounting unavailable", pending=True)
        if not result.ok:
            result.pending = True
        return result
    if status in ("canceled", "cancelled", "rejected", "expired"):
        if not await _claim(pos, pending, None):
            return _result(error="broker exit terminal status not persisted", pending=True)
        _note(pos, "broker_exit_unfilled", f"broker exit {status}; position remains open",
              broker_order_id=str(order["id"]))
        return _result(error=f"broker exit {status}; no confirmed fill")
    return _result(error="broker exit awaiting confirmed fill", pending=True)


async def settle_or_request_close(pos, reason="manual", *, submit=None, quantity=None,
                                  detail="", event=""):
    """Submit once, persist its id, and book only its confirmed cumulative fill.

    `submit`, when supplied, is a no-argument coroutine returning
    (order, status), where status is 'ok', 'error:...', or 'throttled'.
    Callers already managing a sliced order can supply its submit function.
    """
    from app.brokers.accounts import bind_for_user, should_skip_unresolved
    from app.brokers.route_guard import check_route
    uid = str(pos.get("user_id") or "")
    if not uid or not pos.get("id") or pos.get("broker") != "alpaca":
        return _result(error="broker exit requires an identified Alpaca row")
    if should_skip_unresolved(uid):
        return _result(error="broker exit book unresolved")
    with bind_for_user(uid) as account:
        if not _bound_book_verified(uid, account):
            return _result(error="broker exit book transport unverified")
        try:
            ok, _ = check_route(uid)
        except Exception:
            ok = False
        if not ok:
            return _result(error="broker exit route unverified")
        payload = pos.get("source_payload") or {}
        pending = payload.get(PENDING_KEY) if isinstance(payload, dict) else None
        if pending is not None:
            if not isinstance(pending, dict) or not pending.get("started_at"):
                return _result(error="broker exit intent malformed; inspect order", pending=True)
            oid = pending.get("order_id")
            if not oid:
                # A request might have reached the venue before the response
                # was lost. Without its identity, automatic retry is unsafe.
                _note(pos, "broker_exit_unknown", "submitted exit has no verified order id; no resubmission")
                return _result(error="broker exit submission outcome unknown; inspect broker orders", pending=True)
            try:
                order, error = await _read_order(str(oid))
            except Exception:
                return _result(error="pending broker exit order read unavailable", pending=True)
            if error or order is None:
                return _result(error="pending broker exit order read unavailable", pending=True)
            if str(order.get("id") or "") != str(oid):
                return _result(error="pending broker exit order identity mismatch", pending=True)
            return await _settle(pos, order, pending, str(pending.get("reason") or reason))
        try:
            requested = float(quantity if quantity is not None else pos["quantity"])
            if not math.isfinite(requested) or requested <= 0:
                raise ValueError("bad quantity")
        except (KeyError, ValueError, TypeError):
            return _result(error="broker exit quantity invalid")
        if not await _verify_exit_quantity(pos, requested, full_liquidation=submit is None):
            _note(pos, "broker_exit_quantity_unverified",
                  "broker inventory does not uniquely match intended exit; submission blocked")
            return _result(error="broker exit inventory quantity or ownership unverified")
        intent = {"intent_id": uuid.uuid4().hex, "started_at": datetime.now(timezone.utc).isoformat(),
                  "reason": reason, "quantity": requested, "order_id": None}
        if detail:
            intent["detail"] = str(detail)
        if event:
            intent["event"] = str(event)
        if not await _claim(pos, None, intent):
            return _result(error="broker exit intent not claimed; submission blocked", pending=True)
        try:
            if submit is None:
                from app.agents.position_monitor import _throttled_liquidate
                order, status = await _throttled_liquidate(
                    str(pos["ticker"]), asset_type=str(pos.get("asset_type") or "stock"), user_id=uid)
            else:
                order, status = await submit()
        except Exception:  # noqa: BLE001 -- persisted intent prevents blind retries
            return _result(error="broker exit submission outcome unknown", pending=True)
        if status in ("throttled", "circuit_open") or str(status).startswith("deferred:"):
            await _claim(pos, intent, None)
            return _result(error=f"broker exit {status}")
        if status != "ok" or not isinstance(order, dict) or not order.get("id"):
            _note(pos, "broker_exit_unknown", "exit submission unverified; durable intent retained")
            return _result(error="broker exit submission unverified; no resubmission", pending=True)
        linked = {**intent, "order_id": str(order["id"])}
        if not await _claim(pos, intent, linked):
            _note(pos, "broker_exit_receipt_unlinked", "exit order accepted but receipt link failed; inspect order",
                  broker_order_id=str(order["id"]))
            return _result(error="broker exit order link failed", pending=True)
        _note(pos, "broker_exit_submitted", "exit order submitted; execution not assumed",
              broker_order_id=str(order["id"]))
        return await _settle(pos, order, linked, reason)


async def reconcile_broker_close(pos):
    """Only a unique, fully matching closing order can reconcile absence.

    Rows with pending intent use their exact persisted order id. Without
    one, multiple candidate closing orders are ambiguous, not summed or
    guessed. Quantity identity is required for the unlinked full close.
    """
    pending = (pos.get("source_payload") or {}).get(PENDING_KEY)
    if pending is not None:
        return await settle_or_request_close(pos)
    from app.brokers.accounts import bind_for_user, should_skip_unresolved
    from app.brokers.route_guard import check_route
    uid = str(pos.get("user_id") or "")
    if not uid or should_skip_unresolved(uid) or _stamp(pos.get("entry_at")) is None:
        return _result(error="broker close reconciliation identity unavailable")
    with bind_for_user(uid) as account:
        if not _bound_book_verified(uid, account):
            return _result(error="broker close reconciliation book transport unverified")
        try:
            ok, _ = check_route(uid)
            if not ok:
                return _result(error="broker close reconciliation route unverified")
            orders = await _read_closing_orders(pos)
        except Exception:
            return _result(error="broker close order history unavailable")
        if orders is None:
            return _result(error="broker close order history unavailable")
        matches = []
        for order in orders:
            if not _matches(pos, order):
                continue
            try:
                filled = float(order.get("filled_qty") or 0)
                expected = float(pos["quantity"])
            except (ValueError, TypeError, KeyError):
                continue
            if (str(order.get("status") or "").lower() == "filled"
                    and filled > 0 and math.isfinite(filled)
                    and abs(filled - expected) <= max(1e-9, expected * 1e-8)):
                matches.append(order)
        if len(matches) != 1:
            return _result(error="broker close receipt absent or ambiguous; ledger remains open", pending=True)
        return await _record(pos, matches[0], "alpaca_external")
