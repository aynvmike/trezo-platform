"use server";

import { revalidatePath } from "next/cache";
import { createClient } from "@/lib/supabase/server";
import { getOwnerBookKeys, bookQueryKeys } from "@/lib/books";

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

  // rv:web-pages sweep: the position may sit in ANY of the caller's books
  // (0047: user_id is the book key), and the Trading page now lists all
  // of them. RLS already limits the update to the caller's own books.
  const books = await getOwnerBookKeys(supabase, user.id);
  if (books.failure) return; // logged in getOwnerBookKeys; do not guess a book
  await supabase
    .from("paper_positions")
    .update({ close_requested: true })
    .eq("id", positionId)
    .in("user_id", bookQueryKeys(books.data))
    .eq("status", "open");

  revalidatePath("/dashboard/paper");
}
