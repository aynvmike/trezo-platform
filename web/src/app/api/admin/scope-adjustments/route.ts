import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { requireOwner } from "@/lib/auth-guards";

export const dynamic = "force-dynamic";

/**
 * GET /api/admin/scope-adjustments?limit=N
 * Owner-gated. Returns the most recent APPLIED scope adjustments from
 * the strategy_scope_adjustments table — feeds the regime popup banner.
 */
export async function GET(request: Request) {
  // ADM-01: owner-only (TREZO_OWNER_USER_IDS allowlist; unset => 403).
  const supabase = createClient();
  const guard = await requireOwner(supabase);
  if (!guard.ok) return guard.response;
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
