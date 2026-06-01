import { NextRequest, NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

/**
 * Expert overrides API - per-stock strategy pins.
 *
 *   GET  /api/expert/overrides       -> list active overrides for the user
 *   POST /api/expert/overrides       -> upsert {ticker, strategy, expires_at, reason}
 *   DELETE /api/expert/overrides?ticker=X -> remove one
 *
 * RLS gates: each user reads/writes only their own rows. Server
 * components hit this same data via the supabase client directly.
 */

const ALLOWED_STRATEGIES = [
  "default", "pattern", "stms", "orb", "extended", "crypto",
  "iv_crush_short", "dividend_capture_long",
];

export async function GET() {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ ok: false, error: "Not signed in." }, { status: 401 });
  }
  const { data, error } = await supabase
    .from("stock_strategy_overrides")
    .select("id, ticker, strategy, reason, expires_at, created_at")
    .eq("user_id", user.id)
    .order("created_at", { ascending: false });
  if (error) {
    return NextResponse.json({ ok: false, error: error.message }, { status: 200 });
  }
  return NextResponse.json({ ok: true, rows: data ?? [] });
}

export async function POST(req: NextRequest) {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ ok: false, error: "Not signed in." }, { status: 401 });
  }
  const body = await req.json().catch(() => ({}));
  const ticker = String(body.ticker ?? "").trim().toUpperCase();
  const strategy = String(body.strategy ?? "").trim();
  const reason = body.reason ? String(body.reason).trim() : null;
  const expires_at = body.expires_at ? String(body.expires_at) : null;

  if (!ticker || !strategy) {
    return NextResponse.json(
      { ok: false, error: "ticker and strategy are required." },
      { status: 200 }
    );
  }
  if (!ALLOWED_STRATEGIES.includes(strategy)) {
    return NextResponse.json(
      {
        ok: false,
        error: `strategy must be one of: ${ALLOWED_STRATEGIES.join(", ")}`
      },
      { status: 200 }
    );
  }

  const { error } = await supabase
    .from("stock_strategy_overrides")
    .upsert(
      {
        user_id: user.id,
        ticker,
        strategy,
        reason,
        expires_at
      },
      { onConflict: "user_id,ticker" }
    );
  if (error) {
    return NextResponse.json({ ok: false, error: error.message }, { status: 200 });
  }
  return NextResponse.json({ ok: true });
}

export async function DELETE(req: NextRequest) {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ ok: false, error: "Not signed in." }, { status: 401 });
  }
  const ticker = (req.nextUrl.searchParams.get("ticker") ?? "").trim().toUpperCase();
  if (!ticker) {
    return NextResponse.json({ ok: false, error: "ticker is required." }, { status: 200 });
  }
  const { error } = await supabase
    .from("stock_strategy_overrides")
    .delete()
    .eq("user_id", user.id)
    .eq("ticker", ticker);
  if (error) {
    return NextResponse.json({ ok: false, error: error.message }, { status: 200 });
  }
  return NextResponse.json({ ok: true });
}
