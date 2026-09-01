import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { requireOwner } from "@/lib/auth-guards";

export const dynamic = "force-dynamic";

const AGENTS_BASE = process.env.AGENTS_BASE_URL ?? "http://localhost:8001";

/**
 * POST /api/wheel/reconcile
 *
 * Owner-gated. Triggers an immediate reconciliation pass — any open
 * modeled Wheel leg on Trezo's options_positions table that has no
 * matching contract at the broker gets closed_manual with a
 * "Reconciled — not present at broker" note. Use to flush phantom
 * rows after wiping the paper account or switching brokers.
 */
export async function POST() {
  // ADM-04: owner-only (TREZO_OWNER_USER_IDS allowlist; unset => 403).
  const supabase = createClient();
  const guard = await requireOwner(supabase);
  if (!guard.ok) return guard.response;
  try {
    const r = await fetch(`${AGENTS_BASE}/wheel/reconcile`, {
      method: "POST",
      cache: "no-store",
      signal: AbortSignal.timeout(20_000)
    });
    return NextResponse.json(await r.json());
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Unreachable";
    return NextResponse.json(
      { ok: false, error: `${msg}. Make sure the agents service is running on port 8001.` },
      { status: 200 }
    );
  }
}
