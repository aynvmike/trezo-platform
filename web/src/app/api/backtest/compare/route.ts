import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

const AGENTS_BASE = process.env.AGENTS_BASE_URL ?? "http://localhost:8001";

/**
 * GET /api/backtest/compare?symbol=AMD&tcs_threshold=700&stop_pct=0.05&target_pct=0.10
 *
 * Runs every directional strategy against a symbol's history and reports
 * which one performed best for that symbol. The winning strategy's run is
 * persisted to `backtest_runs` so the saved history stays meaningful
 * (one row per symbol, not six).
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
      tcs_threshold: tcs,
      stop_pct: stopPct,
      target_pct: targetPct
    });
    const r = await fetch(`${AGENTS_BASE}/backtest/compare?${qs.toString()}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(120_000)
    });
    const body = await r.json();

    // Persist only the winning strategy so the history is one row per symbol.
    if (
      body &&
      !body.error &&
      Array.isArray(body.strategies) &&
      body.best_strategy
    ) {
      const winner = body.strategies.find(
        (s: { strategy: string }) => s.strategy === body.best_strategy
      );
      if (winner) {
        try {
          await supabase.from("backtest_runs").insert({
            user_id: user.id,
            symbol,
            strategy: winner.strategy,
            tcs_threshold: Number(tcs),
            stop_pct: Number(stopPct),
            target_pct: Number(targetPct),
            period: "2y",
            bars: winner.bars ?? 0,
            trades: winner.trades ?? 0,
            win_rate: winner.win_rate ?? 0,
            profit_factor: winner.profit_factor ?? 0,
            expectancy_pct: winner.expectancy_pct ?? 0,
            total_return_pct: winner.total_return_pct ?? 0,
            max_drawdown_pct: winner.max_drawdown_pct ?? 0
          });
        } catch {
          /* persistence is best-effort — never fail the response over it */
        }
      }
    }

    return NextResponse.json(body);
  } catch (err) {
    const msg =
      err instanceof Error ? err.message : "Backtest service unreachable";
    return NextResponse.json(
      { error: `${msg}. Make sure the agents service is running on port 8001.` },
      { status: 200 }
    );
  }
}
