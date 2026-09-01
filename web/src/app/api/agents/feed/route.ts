import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { requireUser } from "@/lib/auth-guards";

export const dynamic = "force-dynamic";

const AGENTS_BASE = process.env.AGENTS_BASE_URL ?? "http://localhost:8001";

/**
 * GET /api/agents/feed → recent agent_messages across all agents.
 * Always returns `{ messages: [...] }` even on upstream failure so the UI
 * never tries to `.map()` over a non-array.
 */
export async function GET(request: Request) {
  // AUTH-06: this route was reachable with no session at all.
  const supabase = createClient();
  const guard = await requireUser(supabase);
  if (!guard.ok) return guard.response;

  const { searchParams } = new URL(request.url);
  const limit = searchParams.get("limit") ?? "50";
  try {
    const r = await fetch(`${AGENTS_BASE}/agents/feed/recent?limit=${limit}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(8000)
    });
    const body = await r.json().catch(() => null);
    const messages =
      body && Array.isArray((body as { messages?: unknown }).messages)
        ? (body as { messages: unknown[] }).messages
        : [];
    if (!r.ok) {
      return NextResponse.json(
        { messages: [], error: `Agents service returned ${r.status}` },
        { status: 200 }
      );
    }
    return NextResponse.json({ messages });
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Agents service unreachable";
    return NextResponse.json({ messages: [], error: msg }, { status: 200 });
  }
}
