import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { requireOwner } from "@/lib/auth-guards";

export const dynamic = "force-dynamic";

const AGENTS_BASE = process.env.AGENTS_BASE_URL ?? "http://localhost:8001";

/**
 * POST /api/wheel/reconcile
 *
 * Owner-gated. Triggers an immediate reconciliation pass — any open
 * modeled Wheel leg on Trezo's options_positions table that has no
 * matching contract at the broker gets closed_manual with a
 * "Reconciled — not present at broker" note. Use to flush phantom
 * rows after wiping the paper account or switching brokers.
 */
export async function POST(request: Request) {
  // ADM-04: owner-only (TREZO_OWNER_USER_IDS allowlist; unset => 403).
  const supabase = createClient();
  const guard = await requireOwner(supabase);
  if (!guard.ok) return guard.response;
  let accountKey: string;
  try {
    const body = await request.json() as { account_key?: unknown };
    accountKey = typeof body.account_key === "string" ? body.account_key.trim() : "";
  } catch { return NextResponse.json({ ok: false, error: "Expected an account_key in JSON." }, { status: 400 }); }
  if (!accountKey) return NextResponse.json({ ok: false, error: "Select the account to reconcile." }, { status: 400 });
  const { data: owned, error } = await supabase.from("trading_accounts")
    .select("account_key").eq("owner_id", guard.user.id).eq("account_key", accountKey).eq("is_active", true).maybeSingle();
  if (error) return NextResponse.json({ ok: false, error: "Account ownership could not be verified." }, { status: 503 });
  if (!owned) return NextResponse.json({ ok: false, error: "Account not found." }, { status: 404 });
  try {
    const r = await fetch(`${AGENTS_BASE}/wheel/reconcile?user_id=${encodeURIComponent(accountKey)}`, {
      method: "POST",
      cache: "no-store",
      signal: AbortSignal.timeout(20_000)
    });
    return NextResponse.json(await r.json(), { status: r.status });
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Unreachable";
    return NextResponse.json(
      { ok: false, error: `${msg}. Make sure the agents service is running on port 8001.` },
      { status: 200 }
    );
  }
}
