"""Entry cost provenance from broker receipts, with explicit pending estimates.

Never infer a fill from a quote. Crypto cost per owned coin includes the
measured fee-in-kind shortfall once an exclusive wallet arrival is known.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math


@dataclass(frozen=True)
class EntryBasis:
    quantity: float
    price: float
    metadata: dict
    record_position: bool = True


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) and value > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def _symbol(value, asset_type):
    value = str(value or "").upper().strip().replace("/", "")
    if asset_type == "crypto" and not value.endswith("USD"):
        value += "USD"
    return value


def entry_basis(order, *, order_id, ticker, asset_type, side,
                requested_quantity, reference_price, arrival=None, now=None):
    """A complete receipt establishes price; submission alone remains provisional."""
    metadata = {"entry_basis_verified": False, "entry_fees_known": False,
                "entry_price_source": "submission_reference",
                "entry_status": "pending_verification"}
    booked = _number(getattr(arrival, "quantity", None)) if arrival is not None else None
    fallback = EntryBasis(booked or float(requested_quantity), float(reference_price), metadata)
    if not isinstance(order, dict) or not order_id or str(order.get("id")) != str(order_id):
        return fallback
    if (_symbol(order.get("symbol"), asset_type) != _symbol(ticker, asset_type)
            or order.get("side") != ("buy" if side == "long" else "sell")
            or side not in ("long", "short")):
        return fallback
    status = str(order.get("status") or "").lower()
    metadata["entry_order_status"] = status
    qty, price = _number(order.get("filled_qty")), _number(order.get("filled_avg_price"))
    try:
        raw_qty = order.get("filled_qty")
        zero_filled = not isinstance(raw_qty, bool) and float(raw_qty) == 0
    except (TypeError, ValueError, OverflowError):
        zero_filled = False
    if status in ("canceled", "expired", "rejected") and zero_filled:
        return EntryBasis(0.0, float(reference_price), {**metadata, "entry_status": "unfilled_terminal"}, False)
    if status not in ("filled", "canceled", "expired") or qty is None or price is None:
        return fallback
    try:
        filled_at = datetime.fromisoformat(str(order.get("filled_at") or "").replace("Z", "+00:00"))
        clock = now or datetime.now(timezone.utc)
        if filled_at.tzinfo is None or (filled_at - clock).total_seconds() > 2:
            return fallback
    except (TypeError, ValueError):
        return fallback
    requested = _number(requested_quantity)
    if requested is None or qty > requested * 1.000001:
        return fallback
    owned = qty
    basis_price = price
    basis_verified = asset_type == "stock"
    price_source = "broker_fill"
    if asset_type == "crypto" and arrival is not None:
        arrived = _number(getattr(arrival, "quantity", None))
        receipt_qty = _number(getattr(arrival, "receipt_qty", None))
        if (getattr(arrival, "settled", False) and arrived and receipt_qty
                and abs(receipt_qty - qty) <= max(1e-10, qty * 1e-9)
                and arrived <= qty):
            owned = arrived
            basis_price = qty * price / owned
            basis_verified = True
            price_source = "broker_fill_with_measured_net_arrival"
    return EntryBasis(owned, basis_price, {
        **metadata, "entry_status": "filled", "entry_basis_verified": basis_verified,
        "entry_price_source": price_source,
        "broker_entry_filled_qty": qty, "broker_entry_filled_avg_price": price,
        "broker_entry_notional": qty * price,
        "broker_entry_filled_at": filled_at.isoformat(),
        "entry_cost_includes_measured_coin_fee": price_source.endswith("net_arrival"),
    })


async def resolve_entry_basis(order, *, token=None, **kwargs):
    """One bounded strict read after submission; no polling or modeled fill."""
    receipt = order
    if kwargs.get("order_id"):
        try:
            from app.brokers.alpaca import get_order_strict
            fresh, error = await get_order_strict(str(kwargs["order_id"]), token=token)
            if not error and isinstance(fresh, dict):
                receipt = fresh
        except Exception:
            pass  # Provenance below remains explicit; submission is never confirmation.
    return entry_basis(receipt, **kwargs)
