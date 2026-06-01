import { NextResponse } from "next/server";
import { getQuotes } from "@/lib/services/finnhub";

export const dynamic = "force-dynamic";

const DEFAULT_WATCHLIST = ["AMD", "INTC", "CZR", "WMT", "AMSC"];

/**
 * GET /api/quotes[?symbols=AAPL,MSFT]
 * Returns live stock quotes (free-tier Finnhub). Cached upstream for 30s.
 */
export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const symbols = searchParams.get("symbols")?.split(",").map((s) => s.trim()).filter(Boolean);
  try {
    const list = symbols && symbols.length ? symbols : DEFAULT_WATCHLIST;
    const quotes = await getQuotes(list);
    return NextResponse.json({ quotes, fetchedAt: new Date().toISOString() });
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Failed to fetch quotes";
    return NextResponse.json({ error: msg, quotes: [] }, { status: 502 });
  }
}
