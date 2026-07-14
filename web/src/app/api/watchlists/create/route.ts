import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { createWatchlist, addItem } from "@/lib/watchlists";

export const dynamic = "force-dynamic";

/**
 * POST /api/watchlists/create { name, tickers: string[] }
 * Saves a CUSTOM watchlist straight from the Strategy Lab market scan
 * (Mike 2026-07-14). Crypto symbols are typed automatically.
 */
const CRYPTO = new Set([
  "BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "LTC", "LINK", "DOT", "AVAX",
  "XLM", "ALGO", "ATOM"
]);

export async function POST(request: Request) {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ error: "Not signed in." }, { status: 401 });
  }
  let body: { name?: string; tickers?: string[] };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Bad request body." }, { status: 400 });
  }
  const name = (body.name ?? "").trim().slice(0, 60);
  const tickers = Array.from(
    new Set((body.tickers ?? []).map((t) => String(t).toUpperCase().trim()))
  ).filter(Boolean);
  if (!name) {
    return NextResponse.json({ error: "Give the watchlist a name." }, { status: 400 });
  }
  if (tickers.length === 0) {
    return NextResponse.json({ error: "Pick at least one ticker." }, { status: 400 });
  }
  try {
    const list = await createWatchlist(user.id, name);
    let added = 0;
    for (const t of tickers.slice(0, 60)) {
      try {
        await addItem(user.id, list.id, {
          ticker: t,
          asset_type: CRYPTO.has(t) ? "crypto" : "stock"
        });
        added += 1;
      } catch {
        // duplicate or invalid — keep going
      }
    }
    return NextResponse.json({ ok: true, id: list.id, name: list.name, added });
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "Could not create the watchlist." },
      { status: 500 }
    );
  }
}
