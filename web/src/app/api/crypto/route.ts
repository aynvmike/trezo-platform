import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { requireUser } from "@/lib/auth-guards";
import { getCryptoPrices } from "@/lib/services/coingecko";

export const dynamic = "force-dynamic";

/**
 * GET /api/crypto[?symbols=XRP,ETH,SOL]
 * Returns live crypto prices. Cached upstream for 30s.
 */
export async function GET(request: Request) {
  // AUTH-06: this route was reachable with no session at all.
  const supabase = createClient();
  const guard = await requireUser(supabase);
  if (!guard.ok) return guard.response;

  const { searchParams } = new URL(request.url);
  const symbols = searchParams.get("symbols")?.split(",").map((s) => s.trim()).filter(Boolean);
  try {
    const prices = await getCryptoPrices(symbols && symbols.length ? symbols : undefined);
    return NextResponse.json({ prices, fetchedAt: new Date().toISOString() });
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Failed to fetch crypto prices";
    return NextResponse.json({ error: msg, prices: [] }, { status: 502 });
  }
}
