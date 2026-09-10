"""Recognize broker option positions already managed by the Wheel ledger."""
from __future__ import annotations

import asyncio


def broker_option_keys(rows: list[dict]) -> set[tuple[str, str]]:
    # Only a broker-backed single-leg row may claim a venue position.
    from app.paper.trade_qa import occ_for_row
    keys = set()
    for row in rows:
        if row.get("status") != "open":
            continue
        note = str(row.get("notes") or "").lower()
        if not ("placed via alpaca" in note or "imported from broker" in note):
            continue
        if str(row.get("strategy") or "") not in ("wheel_csp", "wheel_cc"):
            continue
        occ = occ_for_row(row)
        if occ:
            keys.add((occ, "short"))
    return keys


async def managed_option_keys(client, user_id: str):
    """None means the ownership read failed; never permission to adopt."""
    def query():
        return (client.table("options_positions")
                .select("id,underlying,option_type,strike,expiration,status,strategy,notes")
                .eq("user_id", str(user_id)).eq("status", "open").execute())
    try:
        rows = (await asyncio.to_thread(query)).data
        if not isinstance(rows, list):
            return None
        return broker_option_keys(rows)
    except Exception:
        return None
