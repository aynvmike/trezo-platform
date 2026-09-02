"""The NO_PRICE_STOP predicate, in one dependency-free place.

NEQ-05 / G3 (audit 2026-09-01): a paper_positions row whose
source_payload carries `no_price_stop: true` is a screen-managed hold --
the dividend ladder -- whose exits are the lane's (dividend cut, payout
breach, recycling ratio), never a price. The Position Monitor consults
this at every price-management site (no stop/target close, no trail or
ladder ratchet, no broker stop, no naked check, no reeval); book_health
skips such rows for its past-stop invariant; and the paper engine
refuses to MERGE an add across the flag boundary.

vf:no-price-stop-monitor: the predicate used to live in position_monitor.
The engine cannot import that module (position_monitor imports the
engine at module top), and book_health's lazy import of it pulled the
whole monitor -- brokers, reevaluator, strategies -- into an agent that
must stay importable on its own. So it lives here, with no imports of
its own, and both sides bind the SAME function: one reading of the flag,
whichever side asks.
"""

from __future__ import annotations


def payload_is_no_price_stop(source_payload) -> bool:
    """Does this source_payload carry the flag? jsonb comes back as a
    dict; a string is parsed defensively. Anything unreadable is NOT
    flagged: an unflagged row keeps today's price management, which is
    the conservative side for every lane except the ladder -- and the
    ladder's rows are written by one executor path with the flag set
    explicitly. Never raises."""
    try:
        sp = source_payload
        if isinstance(sp, str):
            import json as _json
            sp = _json.loads(sp)
        if not isinstance(sp, dict):
            return False
        v = sp.get("no_price_stop")
        if isinstance(v, str):
            return v.strip().lower() in ("1", "true", "yes", "on")
        return bool(v)
    except Exception:  # noqa: BLE001
        return False


def is_no_price_stop(row) -> bool:
    """NEQ-05 / G3: is this row a screen-managed hold with NO price stop?

    True when the row's source_payload carries `no_price_stop` truthy --
    the dividend ladder's contract (dividend_lt_agent sets it on every
    signal; the executor writes the payload onto the row). Such a row is
    held through drawdowns by design: the monitor must not close it on
    price, ratchet a stop onto it, arm one at the broker, or count it
    naked. Manual close_requested, external-fill detection and plain
    bookkeeping are NOT gated by this. Reads only the row. Never raises."""
    try:
        return payload_is_no_price_stop(row.get("source_payload"))
    except Exception:  # noqa: BLE001
        return False
