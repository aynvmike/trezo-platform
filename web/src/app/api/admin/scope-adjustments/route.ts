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
  const requestedLimit = Number(url.searchParams.get("limit") || 1);
  const limit = Number.isFinite(requestedLimit) ? Math.max(1, Math.min(20, Math.floor(requestedLimit))) : 1;
  const { data: books, error: booksError } = await supabase.from("trading_accounts")
    .select("account_key, label").eq("owner_id", guard.user.id);
  if (booksError) return NextResponse.json({ ok: false, error: booksError.message, rows: [] }, { status: 503 });
  const labels = new Map((books ?? []).map((book) => [String(book.account_key), String(book.label ?? "Account")]));
  const requested = url.searchParams.get("account");
  if (requested && !labels.has(requested)) return NextResponse.json({ ok: false, error: "Account not found.", rows: [] }, { status: 404 });
  const keys = requested ? [requested] : [...labels.keys()];
  if (!keys.length) return NextResponse.json({ ok: true, rows: [] });
  const { data, error } = await supabase
    .from("strategy_scope_adjustments")
    .select("id, user_id, action, scope, reason, trigger, severity, status, created_at")
    .in("user_id", keys)
    .eq("status", "applied")
    .order("created_at", { ascending: false })
    .limit(limit);
  if (error) {
    return NextResponse.json({ ok: false, error: error.message, rows: [] }, { status: 503 });
  }
  return NextResponse.json({ ok: true, rows: (data ?? []).map((row) => ({ ...row, book_label: labels.get(String(row.user_id)) })) });
}
