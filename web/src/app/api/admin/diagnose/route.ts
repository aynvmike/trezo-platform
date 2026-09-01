import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { requireOwner } from "@/lib/auth-guards";

export const dynamic = "force-dynamic";
const AGENTS_BASE = process.env.AGENTS_BASE_URL ?? "http://localhost:8001";

/**
 * GET /api/admin/diagnose
 * Owner-gated proxy to the agents service's all-in-one Alpaca diagnostic.
 */
export async function GET() {
  // ADM-01: owner-only (TREZO_OWNER_USER_IDS allowlist; unset => 403).
  const supabase = createClient();
  const guard = await requireOwner(supabase);
  if (!guard.ok) return guard.response;
  try {
    const r = await fetch(`${AGENTS_BASE}/admin/diagnose`, {
      cache: "no-store",
      signal: AbortSignal.timeout(20_000)
    });
    return NextResponse.json(await r.json());
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Unreachable";
    return NextResponse.json(
      { ok: false, error: `${msg}. Agents service offline on port 8001.` },
      { status: 200 }
    );
  }
}
