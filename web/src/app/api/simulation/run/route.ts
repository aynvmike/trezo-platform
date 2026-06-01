import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import {
  getOrSeedDefaultWatchlist,
  getWatchlist
} from "@/lib/watchlists";

export const dynamic = "force-dynamic";

const AGENTS_BASE = process.env.AGENTS_BASE_URL ?? "http://localhost:8001";

/**
 * GET /api/simulation/run
 *
 * Query params:
 *   watchlist_id (optional) — which watchlist to simulate; defaults to
 *                              the user's default ("Core Winners").
 *   days, starting_equity, tcs_threshold, stop_pct, target_pct.
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
  const wlId = searchParams.get("watchlist_id");

  let tickers: string[] = [];
  if (wlId) {
    const wl = await getWatchlist(user.id, wlId);
    if (!wl) {
      return NextResponse.json(
        { error: "Watchlist not found or not yours." },
        { status: 404 }
      );
    }
    tickers = wl.items
      .filter((i) => i.asset_type !== "option")
      .map((i) => i.ticker);
  } else {
    const { items } = await getOrSeedDefaultWatchlist(user.id);
    tickers = items
      .filter((i) => i.asset_type !== "option")
      .map((i) => i.ticker);
  }

  if (tickers.length === 0) {
    return NextResponse.json(
      { error: "That watchlist is empty. Add a ticker to simulate." },
      { status: 400 }
    );
  }

  const days = searchParams.get("days") ?? "7";
  const starting = searchParams.get("starting_equity") ?? "10000";
  const tcs = searchParams.get("tcs_threshold") ?? "650";
  const sp = searchParams.get("stop_pct") ?? "0.05";
  const tp = searchParams.get("target_pct") ?? "0.10";
  const compareAll = (searchParams.get("compare_all") ?? "true").toLowerCase();

  try {
    const qs = new URLSearchParams({
      symbols: tickers.join(","),
      days,
      starting_equity: starting,
      tcs_threshold: tcs,
      stop_pct: sp,
      target_pct: tp,
      compare_all: compareAll === "false" ? "false" : "true"
    });
    const r = await fetch(`${AGENTS_BASE}/simulation/run?${qs.toString()}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(180_000)
    });
    return NextResponse.json(await r.json());
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Unreachable";
    return NextResponse.json(
      { error: `${msg}. Make sure the agents service is running on port 8001.` },
      { status: 200 }
    );
  }
}
