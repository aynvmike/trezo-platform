import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";
const AGENTS_BASE = process.env.AGENTS_BASE_URL ?? "http://localhost:8001";

/**
 * GET /api/admin/settings-audit
 * Auth-gated proxy. Pulls the Bot Tuning row from Supabase and asks
 * each agent what it's *actually* using right now — surfaces drift.
 */
export async function GET() {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ ok: false, error: "Not signed in." }, { status: 401 });
  }
  try {
    const r = await fetch(`${AGENTS_BASE}/admin/settings-audit`, {
      cache: "no-store",
      signal: AbortSignal.timeout(15_000)
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
