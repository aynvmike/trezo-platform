import { NextResponse } from "next/server";
import type { SupabaseClient } from "@supabase/supabase-js";

/** Mutating a book always requires an explicit, independently owned key. */
export async function requireOwnedBook(supabase: SupabaseClient, ownerId: string, requested: unknown): Promise<
  { ok: true; key: string } | { ok: false; response: NextResponse }
> {
  const key = typeof requested === "string" ? requested.trim() : "";
  if (!key) return { ok: false, response: NextResponse.json({ ok: false, error: "Select the account to edit." }, { status: 400 }) };
  const { data, error } = await supabase.from("trading_accounts").select("account_key")
    .eq("owner_id", ownerId).eq("account_key", key).eq("is_active", true).maybeSingle();
  if (error) return { ok: false, response: NextResponse.json({ ok: false, error: "Account ownership could not be verified." }, { status: 503 }) };
  if (!data) return { ok: false, response: NextResponse.json({ ok: false, error: "Account not found." }, { status: 404 }) };
  return { ok: true, key };
}
