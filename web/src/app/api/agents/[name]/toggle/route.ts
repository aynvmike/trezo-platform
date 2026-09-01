import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { requireOwner } from "@/lib/auth-guards";

export const dynamic = "force-dynamic";

const AGENTS_BASE = process.env.AGENTS_BASE_URL ?? "http://localhost:8001";

export async function POST(
  request: Request,
  { params }: { params: { name: string } }
) {
  // Owner guard — toggling an agent on/off is a global state change.
  // ADM-02: owner-only (TREZO_OWNER_USER_IDS allowlist; unset => 403).
  const supabase = createClient();
  const guard = await requireOwner(supabase);
  if (!guard.ok) return guard.response;

  try {
    const body = await request.json();
    const r = await fetch(`${AGENTS_BASE}/agents/${encodeURIComponent(params.name)}/toggle`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
      signal: AbortSignal.timeout(8000)
    });
    const j = await r.json();
    return NextResponse.json(j, { status: r.status });
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Toggle failed" },
      { status: 502 }
    );
  }
}
