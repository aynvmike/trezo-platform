import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

const AGENTS_BASE = process.env.AGENTS_BASE_URL ?? "http://localhost:8001";

/**
 * POST /api/wheel/reconcile
 *
 * Auth-gated. Triggers an immediate reconciliation pass — any open
 * modeled Wheel leg on Trezo's options_positions table that has no
 * matching contract at the broker gets closed_manual with a
 * "Reconciled — not present at broker" note. Use to flush phantom
 * rows after wiping the paper account or switching brokers.
 */
export async function POST() {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ ok: false, error: "Not signed in." }, { status: 401 });
  }
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
