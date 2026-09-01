import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { requireOwner } from "@/lib/auth-guards";

export const dynamic = "force-dynamic";

const AGENTS_BASE = process.env.AGENTS_BASE_URL ?? "http://localhost:8001";

/** POST /api/lab/teach — push a Strategy Lab run into the agents' shared
 *  memory (Mike 2026-07-14). Structured results already persist to
 *  backtest_runs automatically; this adds recallable memory notes. */
export async function POST(request: Request) {
  // SWEEP-01: owner-only (TREZO_OWNER_USER_IDS allowlist; unset => 403).
  const supabase = createClient();
  const guard = await requireOwner(supabase);
  if (!guard.ok) return guard.response;
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Bad request body." }, { status: 400 });
  }
  try {
    const r = await fetch(`${AGENTS_BASE}/lab/teach`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
      signal: AbortSignal.timeout(20000)
    });
    return NextResponse.json(await r.json());
  } catch {
    return NextResponse.json(
      { error: "The agents service could not be reached." },
      { status: 502 }
    );
  }
}
