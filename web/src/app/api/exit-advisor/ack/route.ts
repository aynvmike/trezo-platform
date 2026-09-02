import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { getOwnerBookKeys, bookQueryKeys } from "@/lib/books";

export const dynamic = "force-dynamic";

/**
 * POST /api/exit-advisor/ack
 *
 * Dismisses an exit-advisor alert by setting acknowledged_at = now().
 * The Exit Advisor agent uses that timestamp to deduplicate — once
 * an alert is dismissed, the bot is free to raise a fresh one if the
 * condition continues to deteriorate.
 *
 * Accepts a multipart form (`alert_id`) so the Dismiss button can be
 * a plain `<form>` without JS. Redirects back to the Trading page
 * after the update.
 */
export async function POST(req: Request) {
  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.redirect(new URL("/sign-in", req.url));
  }

  let alertId: string | null = null;
  try {
    const form = await req.formData();
    const v = form.get("alert_id");
    alertId = typeof v === "string" ? v : null;
  } catch {
    // fall through; redirect anyway
  }

  if (alertId) {
    // rv:web-pages sweep: alerts are keyed by BOOK (0047); the banner now
    // shows every book's alerts, so Dismiss must reach them too. RLS still
    // limits the update to the caller's own books.
    const books = await getOwnerBookKeys(supabase, user.id);
    if (!books.failure) {
      await supabase
        .from("exit_advisor_alerts")
        .update({ acknowledged_at: new Date().toISOString() })
        .eq("id", alertId)
        .in("user_id", bookQueryKeys(books.data));
    }
  }

  return NextResponse.redirect(new URL("/dashboard/paper", req.url));
}
