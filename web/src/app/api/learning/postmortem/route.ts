import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

const AGENTS_BASE = process.env.AGENTS_BASE_URL ?? "http://localhost:8001";

/**
 * POST /api/learning/postmortem
 *
 * Triggers the agents-side post-mortem analyzer for the signed-in
 * user. The agent replays every trade_outcomes row whose
 * postmortem_ran_at is null (or all rows when force=true) against
 * the candle history, computes MFE/MAE/optimal exit, and writes
 * postmortem + postmortem_diagnosis back into the row.
 */
export async function POST(req: Request) {
  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json(
      { ok: false, error: "Not signed in." },
      { status: 401 }
    );
  }

  const url = new URL(req.url);
  const force = url.searchParams.get("force") === "true";
  const qs = new URLSearchParams({ user_id: user.id });
  if (force) qs.set("force", "true");

  try {
    const r = await fetch(
      `${AGENTS_BASE}/learning/postmortem/run?${qs}`,
      {
        method: "POST",
        cache: "no-store",
        signal: AbortSignal.timeout(120_000), // analyzer can be slow
      }
    );
    if (!r.ok) {
      const text = await r.text().catch(() => "");
      return NextResponse.json(
        { ok: false, error: `Agents returned ${r.status}: ${text.slice(0, 200)}` },
        { status: 502 }
      );
    }
    const data = await r.json();
    return NextResponse.json(data);
  } catch (e) {
    return NextResponse.json(
      { ok: false, error: e instanceof Error ? e.message : "Network error" },
      { status: 502 }
    );
  }
}
