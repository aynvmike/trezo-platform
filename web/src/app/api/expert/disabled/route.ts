import { NextRequest, NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

/**
 * Expert disabled list - per-stock "do not trade" blacklist.
 *
 *   GET  /api/expert/disabled      -> list active disables for the user
 *   POST /api/expert/disabled      -> upsert {ticker, reason, expires_at}
 *   DELETE /api/expert/disabled?ticker=X -> remove one
 */

export async function GET() {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ ok: false, error: "Not signed in." }, { status: 401 });
  }
  const { data, error } = await supabase
    .from("stock_disabled")
    .select("id, ticker, reason, expires_at, created_at")
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
  const reason = body.reason ? String(body.reason).trim() : null;
  const expires_at = body.expires_at ? String(body.expires_at) : null;

  if (!ticker) {
    return NextResponse.json(
      { ok: false, error: "ticker is required." },
      { status: 200 }
    );
  }

  const { error } = await supabase
    .from("stock_disabled")
    .upsert(
      {
        user_id: user.id,
        ticker,
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
    .from("stock_disabled")
    .delete()
    .eq("user_id", user.id)
    .eq("ticker", ticker);
  if (error) {
    return NextResponse.json({ ok: false, error: error.message }, { status: 200 });
  }
  return NextResponse.json({ ok: true });
}
