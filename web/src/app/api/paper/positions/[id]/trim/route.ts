import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { getOwnerBookKeys, bookQueryKeys } from "@/lib/books";

export const dynamic = "force-dynamic";

const AGENTS_BASE = process.env.AGENTS_BASE_URL ?? "http://localhost:8001";

/**
 * POST /api/paper/positions/[id]/trim
 *
 * Body: { fraction: 0..1 (exclusive of both), reason?: string }
 *
 * Calls the agents-side `close_partial_position` to sell a fraction
 * of the open position at market. Default fraction is 0.5 (half).
 *
 * Capital recycling primitive Mike 2026-06-01 - powers the "Trim 50%"
 * button on Exit Advisor alert cards when an alert's recommendation
 * is `trim_partial`.
 */
export async function POST(
  request: Request,
  { params }: { params: { id: string } }
) {
  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ ok: false, error: "Not signed in." }, { status: 401 });
  }

  let body: { fraction?: number; reason?: string } = {};
  try {
    body = (await request.json()) as { fraction?: number; reason?: string };
  } catch {
    // Allow form-post fallback for the inline button
    try {
      const form = await request.formData();
      body = {
        fraction: Number(form.get("fraction") ?? 0.5),
        reason: String(form.get("reason") ?? "user_trim"),
      };
    } catch {
      body = {};
    }
  }

  const fraction = Number(body.fraction ?? 0.5);
  const reason = body.reason ?? "user_trim";
  if (!Number.isFinite(fraction) || fraction <= 0 || fraction >= 1) {
    return NextResponse.json(
      { ok: false, error: "fraction must be > 0 and < 1" },
      { status: 400 }
    );
  }

  // Confirm the position sits in one of this person's BOOKS before
  // invoking (rv:web-pages sweep: user_id is the book key since 0047, and
  // the Trading page lists every book). A failed read is a 500, not a 404.
  const books = await getOwnerBookKeys(supabase, user.id);
  if (books.failure) {
    return NextResponse.json({ ok: false, error: `Could not resolve your books: ${books.failure.message}` }, { status: 500 });
  }
  const { data: pos, error: posErr } = await supabase
    .from("paper_positions")
    .select("id, user_id, ticker, asset_type, status")
    .eq("id", params.id)
    .in("user_id", bookQueryKeys(books.data))
    .maybeSingle();
  if (posErr) {
    return NextResponse.json({ ok: false, error: `Position read failed: ${posErr.message}` }, { status: 500 });
  }
  if (!pos) {
    return NextResponse.json({ ok: false, error: "Position not found" }, { status: 404 });
  }
  if (pos.status !== "open") {
    return NextResponse.json({ ok: false, error: "Position is not open" }, { status: 409 });
  }

  // Forward to the agents service. It owns the market-price lookup +
  // the cash/PNL accounting; the web layer is just the auth front door.
  try {
    const r = await fetch(`${AGENTS_BASE}/paper/positions/trim`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        // The BOOK that holds the position, not the person: the agents
        // bind the broker account by this id.
        user_id: pos.user_id,
        position_id: params.id,
        ticker: pos.ticker,
        asset_type: pos.asset_type,
        fraction,
        reason,
      }),
      signal: AbortSignal.timeout(15_000),
    });
    const data = await r.json();
    return NextResponse.json(data, { status: r.ok ? 200 : r.status });
  } catch (e) {
    return NextResponse.json(
      { ok: false, error: e instanceof Error ? e.message : "Network error" },
      { status: 502 }
    );
  }
}
