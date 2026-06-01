import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

const AGENTS_BASE = process.env.AGENTS_BASE_URL ?? "http://localhost:8001";

const ALLOWED = new Set([
  "pattern_detection",
  "stms_scanner",
  "orb_scanner",
  "extended_scanner",
  "crypto_scanner",
  "options_scanner",
  "market_horizon",
  "adaptive_scope",
  "research",
  "market_sentiment",
  "dividend_manager",
  "strategy_discovery"
]);

/**
 * POST /api/agents/run-now/:name
 *
 * Auth-gated proxy to the agents service. Force-ticks the named agent
 * outside its normal schedule. A short health preflight separates
 * "agents service offline" from "scanner is slow" so the user gets a
 * useful error either way.
 */
export async function POST(
  _request: Request,
  { params }: { params: { name: string } }
) {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ ok: false, error: "Not signed in." }, { status: 401 });
  }
  const name = String(params.name ?? "").trim();
  if (!ALLOWED.has(name)) {
    return NextResponse.json(
      { ok: false, error: `Agent "${name}" cannot be force-ticked from the UI.` },
      { status: 400 }
    );
  }

  // Preflight: a 2.5s health check confirms the agents service is up
  // before we wait 60s on the actual tick.
  try {
    const h = await fetch(`${AGENTS_BASE}/health`, {
      cache: "no-store",
      signal: AbortSignal.timeout(2_500)
    });
    if (!h.ok) throw new Error(`Health returned ${h.status}`);
  } catch {
    return NextResponse.json(
      {
        ok: false,
        error:
          "Agents service is not reachable on port 8001 — start it with `cd agents && uv run uvicorn app.main:app --port 8001` and try again."
      },
      { status: 200 }
    );
  }

  try {
    const r = await fetch(`${AGENTS_BASE}/agents/run-now/${encodeURIComponent(name)}`, {
      method: "POST",
      cache: "no-store",
      // 60s — Pattern Detection scans the full market-wide pool which
      // can take ~30-45s on a cold cache.
      signal: AbortSignal.timeout(60_000)
    });
    return NextResponse.json(await r.json());
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Unreachable";
    return NextResponse.json(
      {
        ok: false,
        error: `${msg}. The agent timed out — try again, or hit a lighter scanner first (Market Horizons / Crypto). If it keeps failing, restart the agents service.`
      },
      { status: 200 }
    );
  }
}
