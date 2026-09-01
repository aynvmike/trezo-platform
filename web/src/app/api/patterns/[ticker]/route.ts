import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { requireUser } from "@/lib/auth-guards";

export const dynamic = "force-dynamic";

const AGENTS_BASE = process.env.AGENTS_BASE_URL ?? "http://localhost:8001";

/**
 * GET /api/patterns/[ticker]?asset_type=auto&catalyst=false&iv_rank=&spy_up=
 * Proxies to the agents service.
 */
export async function GET(
  request: Request,
  { params }: { params: { ticker: string } }
) {
  // AUTH-06: this route was reachable with no session at all.
  const supabase = createClient();
  const guard = await requireUser(supabase);
  if (!guard.ok) return guard.response;

  const { searchParams } = new URL(request.url);
  const qs = searchParams.toString();
  const url = `${AGENTS_BASE}/patterns/scan/${encodeURIComponent(params.ticker)}${qs ? "?" + qs : ""}`;

  try {
    const r = await fetch(url, {
      cache: "no-store",
      signal: AbortSignal.timeout(15_000)
    });
    const body = await r.json();
    return NextResponse.json(body, { status: r.status });
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Agents service unreachable";
    return NextResponse.json(
      { error: msg, hint: "Make sure the agents service is running at " + AGENTS_BASE },
      { status: 502 }
    );
  }
}
