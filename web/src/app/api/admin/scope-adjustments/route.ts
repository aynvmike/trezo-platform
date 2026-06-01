import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

export const dynamic = "force-dynamic";

/**
 * GET /api/admin/scope-adjustments?limit=N
 * Auth-gated. Returns the most recent APPLIED scope adjustments from
 * the strategy_scope_adjustments table — feeds the regime popup banner.
 */
export async function GET(request: Request) {
  const supabase = createClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ ok: false, error: "Not signed in." }, { status: 401 });
  }
  const url = new URL(request.url);
  const limit = Math.max(1, Math.min(20, Number(url.searchParams.get("limit") || 1)));
  const { data, error } = await supabase
    .from("strategy_scope_adjustments")
    .select("id, action, scope, reason, trigger, severity, status, created_at")
    .eq("status", "applied")
    .order("created_at", { ascending: false })
    .limit(limit);
  if (error) {
    return NextResponse.json({ ok: false, error: error.message, rows: [] });
  }
  return NextResponse.json({ ok: true, rows: data ?? [] });
}
