import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import {
  getOrSeedDefaultWatchlist,
  addItem
} from "@/lib/watchlists";

export const dynamic = "force-dynamic";

/**
 * POST /api/watchlists/promote
 * Body: { ticker: string }
 *
 * Adds the ticker to the user's default ("Core Winners") watchlist —
 * idempotent: if it's already there, return ok with already_present.
 * Used from the Simulation Lab "Promote →" action so a ticker that
 * tested well can move into the real working watchlist with one tap.
 */
export async function POST(request: Request) {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ error: "Not signed in." }, { status: 401 });
  }

  let body: { ticker?: string };
  try {
    body = (await request.json()) as { ticker?: string };
  } catch {
    return NextResponse.json(
      { error: "Bad request body — expected JSON." },
      { status: 400 }
    );
  }

  const ticker = (body.ticker ?? "").trim().toUpperCase();
  if (!ticker) {
    return NextResponse.json(
      { error: "ticker is required." },
      { status: 400 }
    );
  }

  const { list, items } = await getOrSeedDefaultWatchlist(user.id);

  if (items.some((i) => i.ticker.toUpperCase() === ticker)) {
    return NextResponse.json({
      ok: true,
      already_present: true,
      watchlist: list.name
    });
  }

  try {
    await addItem(user.id, list.id, { ticker });
  } catch (e) {
    return NextResponse.json(
      { error: e instanceof Error ? e.message : "could not add ticker" },
      { status: 500 }
    );
  }

  return NextResponse.json({
    ok: true,
    already_present: false,
    watchlist: list.name
  });
}
