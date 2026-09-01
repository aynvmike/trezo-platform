"""KINDRIP → ISO 20022 PaymentInstruction bridge.

When the KINDRIP agent successfully processes a child's scheduled
contribution, we want a draft pain.001 record sitting in
`payment_instructions` so:

  1. The audit trail builds up before banking goes live - on day one
     of real ACH/RTP/FedNow integration, we already have months of
     correctly-shaped instructions to reconcile against.
  2. Mike can see what would have wired, with the exact ISO 20022
     fields, in the dashboard ledger.
  3. Future reconciliation work (camt.053 statements) plugs into a
     ledger that's already populated.

Today, KINDRIP doesn't actually move external money - the child's
balance is debited from the parent's *internal* cash. So the draft
instructions live in 'draft' state. When real banking goes live, the
KINDRIP engine flips the status to 'queued' and the wire submission
moves it through 'submitted' -> 'accepted' -> 'settled'.

Failures are swallowed - the contribution itself already succeeded
when we get here; the audit record is a nice-to-have, not a
blocker.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from typing import Any, Optional

import structlog

from app.config import get_settings
from app.payments.iso20022 import (
    Amount, Party, PaymentInstruction, persist,
)

log = structlog.get_logger("trezo.payments.kindrip_bridge")

# Placeholder routing details used in 'draft' state. When real banking
# is wired, these are replaced by the parent's verified bank link
# (Plaid / direct connection) for the debtor and the child's
# custodian-of-record for the creditor.
_PLACEHOLDER_AGENT = "USABA"
_PLACEHOLDER_DEBTOR_AGENT_ID = "000000000"
_PLACEHOLDER_CREDITOR_AGENT_ID = "000000000"


def _supabase():
    s = get_settings()
    if not s.supabase_url or not s.supabase_service_role_key:
        return None
    try:
        from supabase import create_client
        return create_client(s.supabase_url, s.supabase_service_role_key)
    except Exception:  # noqa: BLE001
        return None


_PLACEHOLDER_PARENT = "Trezo Parent"


async def _parent_name(client, user_id: str) -> str:
    """Resolve the parent's display name from profiles, falling back
    to a clean placeholder ONLY when display_name is genuinely empty.

    MIG-02 (audit 2026-09-01): this selected `full_name, email` --
    neither column exists on profiles (0001 defines `display_name`;
    email lives in auth.users), so PostgREST rejected the query on
    every run, the error was swallowed, and every draft pain.001 was
    stamped 'Trezo Parent'. The read failure is now logged so a schema
    drift like this is visible instead of silently becoming the name.
    """
    def _sync():
        return (
            client.table("profiles")
            .select("display_name")
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
    try:
        res = await asyncio.to_thread(_sync)
    except Exception as e:  # noqa: BLE001
        log.warning("kindrip_bridge.parent_name_failed",
                    user_id=user_id, error=str(e)[:200])
        return _PLACEHOLDER_PARENT
    err = getattr(res, "error", None) if res is not None else None
    if err:
        log.warning("kindrip_bridge.parent_name_failed",
                    user_id=user_id, error=str(err)[:200])
        return _PLACEHOLDER_PARENT
    row = (res.data if res is not None else None) or {}
    name = str(row.get("display_name") or "").strip()
    return name or _PLACEHOLDER_PARENT


async def record_kindrip_draft(
    *,
    user_id: str,
    child_row: dict,
    contribution_usd: float,
    seed_usd: float,
    related_table: str = "kindrip_children",
) -> Optional[str]:
    """Build + persist a draft pain.001 PaymentInstruction for one
    successful KINDRIP run. Returns the inserted row id."""
    if contribution_usd <= 0 and seed_usd <= 0:
        return None  # nothing to record

    client = _supabase()
    if not client:
        return None

    try:
        parent_name = await _parent_name(client, user_id)
        child_name = (child_row.get("child_name") or "Future Index Account").strip()
        child_id = child_row.get("id")

        total = round(float(contribution_usd) + float(seed_usd), 2)
        if total <= 0:
            return None

        # Build the canonical instruction.
        debtor = Party(
            name=parent_name,
            account_id=f"TREZO-PARENT-{user_id[:8]}",
            account_type="OTHR",
            agent_clearing_system=_PLACEHOLDER_AGENT,
            agent_clearing_id=_PLACEHOLDER_DEBTOR_AGENT_ID,
            country="US",
        )
        creditor = Party(
            name=f"{child_name} Future Index Account",
            account_id=f"TREZO-FIA-{(child_id or 'unknown')[:8]}",
            account_type="OTHR",
            agent_clearing_system=_PLACEHOLDER_AGENT,
            agent_clearing_id=_PLACEHOLDER_CREDITOR_AGENT_ID,
            country="US",
        )

        # Remittance text spells out what hit the child's account.
        parts: list[str] = []
        if contribution_usd > 0:
            parts.append(f"contribution ${contribution_usd:.2f}")
        if seed_usd > 0:
            parts.append(f"federal seed ${seed_usd:.2f}")
        remit = (
            f"KINDRIP {child_name}: " + ", ".join(parts)
            if parts else f"KINDRIP {child_name}"
        )

        pi = PaymentInstruction(
            user_id=user_id,
            flow="kindrip_contribution",
            amount=Amount(value=total, currency="USD"),
            requested_execution_date=date.today(),
            debtor=debtor,
            creditor=creditor,
            local_instrument="FNW",     # FedNow is the natural target
            category_purpose="INTC",    # intra-company / dependent
            purpose_code="EDUC",
            service_level="INST",       # instant settlement once real
            remittance_info_unstructured=remit,
            related_table=related_table,
            related_id=str(child_id) if child_id else None,
            status="draft",
        )

        new_id = await persist(pi, render_xml=True)
        log.info("kindrip_bridge.recorded",
                 user_id=user_id, child=child_name,
                 amount=total, instruction_id=new_id)
        return new_id
    except Exception as e:  # noqa: BLE001
        log.warning("kindrip_bridge.failed", error=str(e)[:200])
        return None
