import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { requireUser } from "@/lib/auth-guards";
import { cacheGetOrSet } from "@/lib/cache";

export const dynamic = "force-dynamic";

type FinnhubMatch = {
  symbol: string;
  description: string;
  type: string;
};

type FinnhubSearch = { count: number; result: FinnhubMatch[] };

/**
 * GET /api/tickers/search?q=APPL
 * Returns Finnhub symbol matches. Cached 24h.
 */
export async function GET(request: Request) {
  // AUTH-06: this route was reachable with no session at all.
  const supabase = createClient();
  const guard = await requireUser(supabase);
  if (!guard.ok) return guard.response;

  const { searchParams } = new URL(request.url);
  const q = (searchParams.get("q") ?? "").trim();
  if (q.length < 1) return NextResponse.json({ matches: [] });

  const key = process.env.FINNHUB_API_KEY;
  if (!key) {
    return NextResponse.json(
      { error: "FINNHUB_API_KEY not set on server", matches: [] },
      { status: 503 }
    );
  }

  try {
    const matches = await cacheGetOrSet<FinnhubMatch[]>(
      `tickers:search:${q.toLowerCase()}`,
      60 * 60 * 24,
      async () => {
        const url = `https://finnhub.io/api/v1/search?q=${encodeURIComponent(q)}&token=${key}`;
        const r = await fetch(url, {
          cache: "no-store",
          signal: AbortSignal.timeout(8000)
        });
        if (!r.ok) throw new Error(`Finnhub ${r.status}`);
        const j = (await r.json()) as FinnhubSearch;
        return (j.result ?? [])
          .filter((m) => m.type === "Common Stock" || m.type === "ETF" || m.type === "ETP")
          .slice(0, 10);
      }
    );
    return NextResponse.json({ matches });
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Search failed";
    return NextResponse.json({ error: msg, matches: [] }, { status: 502 });
  }
}
