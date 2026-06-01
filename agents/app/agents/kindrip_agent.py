"""KINDRIP Agent.

Phase 9b. The 15th agent. Every 6 hours it walks the KINDRIP children and
runs any contribution that has come due - moving the parent's scheduled
amount in, applying the one-time federal seed once funding opens, and
auto-investing into the child's index mix. Each run emits a plain-language
summary so the parent (and eventually the child) can see what happened.
"""

from __future__ import annotations

import asyncio

from app.config import get_settings
from app.kindrip.engine import process_child

from .base import Agent, AgentMessage


def _supabase():
    s = get_settings()
    if not s.supabase_url or not s.supabase_service_role_key:
        return None
    try:
        from supabase import create_client
        return create_client(s.supabase_url, s.supabase_service_role_key)
    except Exception:  # noqa: BLE001
        return None


class KindripAgent(Agent):
    name = "kindrip"
    tick_interval_seconds = 21600  # every 6 hours

    async def tick(self) -> list[AgentMessage]:
        client = _supabase()
        if not client:
            return [AgentMessage(agent=self.name, kind="info",
                                 payload={"note": "Supabase not configured."})]

        def _q():
            return client.table("kindrip_children").select("*").execute()

        try:
            children = (await asyncio.to_thread(_q)).data or []
        except Exception as e:  # noqa: BLE001
            return [AgentMessage(agent=self.name, kind="error",
                                 payload={"error": str(e)})]

        out: list[AgentMessage] = []
        processed = 0

        for child in children:
            try:
                result = await process_child(client, child)
            except Exception as e:  # noqa: BLE001
                out.append(AgentMessage(agent=self.name, kind="error",
                                        payload={"child_id": child.get("id"),
                                                 "error": str(e)}))
                continue
            if result:
                processed += 1
                # ISO 20022 audit trail. We persist a draft pain.001
                # PaymentInstruction so that when real banking goes
                # live, the audit ledger already has months of
                # correctly-shaped instructions. Failures are
                # swallowed - the contribution itself already succeeded.
                instruction_id = None
                try:
                    from app.payments.kindrip_bridge import record_kindrip_draft
                    instruction_id = await record_kindrip_draft(
                        user_id=child.get("user_id"),
                        child_row=child,
                        contribution_usd=float(result.get("contribution_usd") or 0),
                        seed_usd=float(result.get("seed_usd") or 0),
                    )
                except Exception:  # noqa: BLE001
                    instruction_id = None

                out.append(AgentMessage(
                    agent=self.name, kind="info", confidence=1.0,
                    payload={
                        "user_id": child.get("user_id"),
                        "event": "kindrip_contribution",
                        "child_name": result["child_name"],
                        "deposited_usd": result["deposited_usd"],
                        "seed_usd": result["seed_usd"],
                        "contribution_usd": result["contribution_usd"],
                        "invested": result["invested"],
                        "payment_instruction_id": instruction_id,
                        "note": (f"KINDRIP added ${result['deposited_usd']:,.2f} to "
                                 f"{result['child_name']}'s Future Index Account."),
                    },
                ))

        out.append(AgentMessage(
            agent=self.name, kind="info",
            payload={"note": "KINDRIP run complete",
                     "children": len(children), "contributions_made": processed},
        ))
        return out
