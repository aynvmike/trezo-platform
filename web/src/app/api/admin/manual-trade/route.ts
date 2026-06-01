import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";
const AGENTS_BASE = process.env.AGENTS_BASE_URL ?? "http://localhost:8001";

/**
 * POST /api/admin/manual-trade
 * Body: { ticker, side: 'long'|'short', stop_pct?, target_pct? }
 *
 * Manual trade trigger — runs through Risk Manager → Trade Execution →
 * current venue (paper today, live later). Auth-gated.
 */
export async function POST(request: Request) {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ ok: false, error: "Not signed in." }, { status: 401 });
  }
  let body: { ticker?: string; side?: string; stop_pct?: number; target_pct?: number };
  try {
    body = (await request.json()) as typeof body;
  } catch {
    return NextResponse.json({ ok: false, error: "Bad JSON body." }, { status: 400 });
  }
  const ticker = (body.ticker ?? "").trim().toUpperCase();
  if (!/^[A-Z][A-Z0-9.-]{0,9}$/.test(ticker)) {
    return NextResponse.json({ ok: false, error: "Invalid ticker." }, { status: 400 });
  }
  const side = (body.side ?? "long").trim().toLowerCase();
  if (side !== "long" && side !== "short") {
    return NextResponse.json({ ok: false, error: "side must be 'long' or 'short'." }, { status: 400 });
  }
  const qs = new URLSearchParams({
    user_id: user.id,
    ticker,
    side,
    ...(body.stop_pct != null ? { stop_pct: String(body.stop_pct) } : {}),
    ...(body.target_pct != null ? { target_pct: String(body.target_pct) } : {})
  });
  try {
    const r = await fetch(`${AGENTS_BASE}/admin/manual-trade?${qs.toString()}`, {
      method: "POST",
      cache: "no-store",
      signal: AbortSignal.timeout(25_000)
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
