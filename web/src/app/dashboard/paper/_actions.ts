"use server";

import { revalidatePath } from "next/cache";
import { createClient } from "@/lib/supabase/server";

/**
 * QW1 — request a manual close of an open paper position.
 *
 * Sets close_requested = true. The Position Monitor agent honours the
 * flag on its next tick and closes the position at the current market
 * price (reason 'manual'). RLS plus the explicit user_id match ensure a
 * user can only close their own positions.
 */
export async function requestClose(formData: FormData): Promise<void> {
  const positionId = String(formData.get("position_id") ?? "").trim();
  if (!positionId) return;

  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) return;

  await supabase
    .from("paper_positions")
    .update({ close_requested: true })
    .eq("id", positionId)
    .eq("user_id", user.id)
    .eq("status", "open");

  revalidatePath("/dashboard/paper");
}
