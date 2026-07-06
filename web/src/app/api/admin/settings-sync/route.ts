import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";
const AGENTS_BASE = process.env.AGENTS_BASE_URL ?? "http://localhost:8001";

/**
 * POST /api/admin/settings-sync
 * Auth-gated proxy. Clears the agents' settings cache so every consumer
 * re-reads the saved Bot Tuning row, then returns a fresh audit. Drift
 * that survives a sync is real (env override / hardcode) — the response
 * says so (Mike 2026-07-06: "auto fix, or give a reason").
 */
export async function POST() {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ ok: false, error: "Not signed in." }, { status: 401 });
  }
  try {
    const r = await fetch(`${AGENTS_BASE}/admin/settings-sync`, {
      method: "POST",
      cache: "no-store",
      signal: AbortSignal.timeout(15_000),
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
