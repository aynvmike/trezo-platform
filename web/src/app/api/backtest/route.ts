import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

const AGENTS_BASE = process.env.AGENTS_BASE_URL ?? "http://localhost:8001";

/**
 * GET /api/backtest?symbol=AMD&strategy=default&tcs_threshold=700&stop_pct=0.05&target_pct=0.10
 * Proxies a backtest run to the agents service, then persists the run to
 * `backtest_runs` so the history is kept and the agents can learn from it.
 * Auth-guarded — running a backtest is a signed-in user action.
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
  const symbol = (searchParams.get("symbol") ?? "").trim().toUpperCase();
  const strategy = searchParams.get("strategy") ?? "default";
  const tcs = searchParams.get("tcs_threshold") ?? "700";
  const stopPct = searchParams.get("stop_pct") ?? "0.05";
  const targetPct = searchParams.get("target_pct") ?? "0.10";
  if (!symbol) {
    return NextResponse.json(
      { error: "A ticker symbol is required." },
      { status: 400 }
    );
  }

  try {
    const qs = new URLSearchParams({
      symbol,
      strategy,
      tcs_threshold: tcs,
      stop_pct: stopPct,
      target_pct: targetPct
    });
    const r = await fetch(`${AGENTS_BASE}/backtest?${qs.toString()}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(60_000)
    });
    const body = await r.json();

    // Persist a successful run so the history accumulates (best-effort).
    if (body && !body.error && typeof body.trades === "number") {
      try {
        await supabase.from("backtest_runs").insert({
          user_id: user.id,
          symbol,
          strategy,
          tcs_threshold: Number(tcs),
          stop_pct: Number(stopPct),
          target_pct: Number(targetPct),
          period: "2y",
          bars: body.bars ?? 0,
          trades: body.trades ?? 0,
          win_rate: body.win_rate ?? 0,
          profit_factor: body.profit_factor ?? 0,
          expectancy_pct: body.expectancy_pct ?? 0,
          total_return_pct: body.total_return_pct ?? 0,
          max_drawdown_pct: body.max_drawdown_pct ?? 0
        });
      } catch {
        /* persistence is best-effort — never fail the response over it */
      }
    }

    return NextResponse.json(body);
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Backtest service unreachable";
    return NextResponse.json(
      { error: `${msg}. Make sure the agents service is running on port 8001.` },
      { status: 200 }
    );
  }
}
