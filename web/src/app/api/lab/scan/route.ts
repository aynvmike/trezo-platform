import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

const AGENTS_BASE = process.env.AGENTS_BASE_URL ?? "http://localhost:8001";

/**
 * GET /api/lab/scan?sector=XLK&limit=24
 * Market / industry scan for the Strategy Lab (Mike 2026-07-14) — proxies
 * the agents service, which returns movers with 1d/3d moves + volume pace
 * and the sector menu.
 */
export async function GET(request: Request) {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ error: "Not signed in." }, { status: 401 });
  }
  const { searchParams } = new URL(request.url);
  const qs = new URLSearchParams({
    scope: searchParams.get("scope") ?? "market",
    sector: searchParams.get("sector") ?? "",
    limit: searchParams.get("limit") ?? "24"
  });
  try {
    const r = await fetch(`${AGENTS_BASE}/lab/scan?${qs.toString()}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(60000)
    });
    const body = await r.json();
    return NextResponse.json(body);
  } catch {
    return NextResponse.json(
      { error: "The scan service could not be reached — are the agents running?" },
      { status: 502 }
    );
  }
}
