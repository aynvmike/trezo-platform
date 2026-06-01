import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

const AGENTS_BASE = process.env.AGENTS_BASE_URL ?? "http://localhost:8001";

/**
 * POST /api/stocks/reconcile
 *
 * Auth-gated. Triggers a stock-side reconciliation against Alpaca:
 *  - Trezo open paper_positions for stocks get patched to match Alpaca's
 *    actual qty + avg_entry_price (broker truth wins).
 *  - Positions Alpaca has that Trezo doesn't get inserted as tracking
 *    rows.
 *  - Trezo rows for symbols Alpaca holds nothing in get closed.
 *
 * Use after a discrepancy is spotted — e.g. SOFI showing qty 3 on
 * Trezo but qty 7 on Alpaca.
 */
export async function POST() {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ ok: false, error: "Not signed in." }, { status: 401 });
  }
  try {
    const r = await fetch(`${AGENTS_BASE}/stocks/reconcile`, {
      method: "POST",
      cache: "no-store",
      signal: AbortSignal.timeout(30_000)
    });
    return NextResponse.json(await r.json());
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Unreachable";
    return NextResponse.json(
      { ok: false, error: `${msg}. Make sure the agents service is running on port 8001.` },
      { status: 200 }
    );
  }
}
