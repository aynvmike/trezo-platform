import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

const AGENTS_BASE = process.env.AGENTS_BASE_URL ?? "http://localhost:8001";

/**
 * GET /api/paper/positions/[id]/trim-preview
 *
 * Returns position snapshot + four preset previews + cost-basis
 * fraction (house money) + bot-recommended fraction. Powers the
 * TrimDialog's slider + preset buttons. Mike 2026-06-01.
 */
export async function GET(
  _request: Request,
  { params }: { params: { id: string } }
) {
  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ ok: false, error: "Not signed in." }, { status: 401 });
  }
  const qs = new URLSearchParams({
    user_id: user.id,
    position_id: params.id,
  });
  try {
    const r = await fetch(
      `${AGENTS_BASE}/paper/positions/trim-preview?${qs}`,
      { cache: "no-store", signal: AbortSignal.timeout(8000) }
    );
    const data = await r.json();
    return NextResponse.json(data, { status: r.ok ? 200 : r.status });
  } catch (e) {
    return NextResponse.json(
      { ok: false, error: e instanceof Error ? e.message : "Network error" },
      { status: 502 }
    );
  }
}
