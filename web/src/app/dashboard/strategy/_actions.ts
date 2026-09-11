"use server";

import { revalidatePath } from "next/cache";
import { createClient } from "@/lib/supabase/server";

/**
 * QW4 — resolve a Suggest-mode scope adjustment.
 *
 * In Suggest autonomy mode the Adaptive Scope engine records changes with
 * status 'suggested' and does not act on them. This flips a suggestion to
 * 'applied' (approve) or 'dismissed'. The Adaptive Scope agent loads
 * approved rows into the live trading scope on its next tick.
 *
 * The .eq("status", "suggested") guard means only a still-pending row can
 * be resolved — a double click or stale page cannot re-resolve one.
 */
export async function resolveSuggestion(formData: FormData): Promise<void> {
  const rowId = String(formData.get("row_id") ?? "").trim();
  const decision = String(formData.get("decision") ?? "").trim();
  const accountKey = String(formData.get("account_key") ?? "").trim();
  if (!rowId || !accountKey || (decision !== "apply" && decision !== "dismiss")) return;

  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) return;

  const { data: owned, error } = await supabase.from("trading_accounts")
    .select("account_key").eq("owner_id", user.id).eq("account_key", accountKey).eq("is_active", true).maybeSingle();
  if (error || !owned) throw new Error("Account ownership could not be verified.");

  const { error: updateError } = await supabase
    .from("strategy_scope_adjustments")
    .update({ status: decision === "apply" ? "applied" : "dismissed" })
    .eq("id", rowId)
    .eq("user_id", accountKey)
    .eq("status", "suggested");

  if (updateError) throw new Error(`Scope change was not saved: ${updateError.message}`);

  revalidatePath("/dashboard/strategy");
}
