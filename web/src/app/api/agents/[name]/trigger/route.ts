import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { requireOwner } from "@/lib/auth-guards";

export const dynamic = "force-dynamic";

const AGENTS_BASE = process.env.AGENTS_BASE_URL ?? "http://localhost:8001";

export async function POST(
  _request: Request,
  { params }: { params: { name: string } }
) {
  // Owner guard — triggering an agent run is a global state change.
  // ADM-02: owner-only (TREZO_OWNER_USER_IDS allowlist; unset => 403).
  const supabase = createClient();
  const guard = await requireOwner(supabase);
  if (!guard.ok) return guard.response;

  try {
    const r = await fetch(`${AGENTS_BASE}/agents/${encodeURIComponent(params.name)}/trigger`, {
      method: "POST",
      cache: "no-store",
      signal: AbortSignal.timeout(30_000)
    });
    const j = await r.json();
    return NextResponse.json(j, { status: r.status });
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Trigger failed" },
      { status: 502 }
    );
  }
}
