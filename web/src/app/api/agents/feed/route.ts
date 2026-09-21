import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { requireUser } from "@/lib/auth-guards";
import { messageBelongsToBooks } from "@/lib/agent-book-scope";

export const dynamic = "force-dynamic";

/**
 * Read activity with the caller's session, including older bus messages
 * whose account key is in payload. Failed reads are visibly unavailable.
 */
export async function GET(request: Request) {
  // AUTH-06: this route was reachable with no session at all.
  const supabase = createClient();
  const guard = await requireUser(supabase);
  if (!guard.ok) return guard.response;

  const { searchParams } = new URL(request.url);
  const requestedLimit = Number(searchParams.get("limit") ?? 50);
  const limit = Number.isFinite(requestedLimit) ? Math.max(1, Math.min(200, Math.floor(requestedLimit))) : 50;
  const selectedBook = searchParams.get("account")?.trim() || undefined;
  try {
    const { data: books, error: booksError } = await supabase.from("trading_accounts")
      .select("account_key, label").eq("owner_id", guard.user.id);
    if (booksError) throw new Error(`Unable to load your accounts: ${booksError.message}`);
    const keys = (books ?? []).map((book) => String(book.account_key));
    if (selectedBook && !keys.includes(selectedBook)) return NextResponse.json({ messages: [], error: "Account not found." }, { status: 404 });
    const labels = new Map((books ?? []).map((book) => [String(book.account_key), String(book.label ?? "Account")]));
    const { data, error } = await supabase.from("agent_messages")
      .select("id, user_id, agent_name, kind, confidence, payload, created_at")
      .or(`user_id.in.(${[...new Set([...keys, guard.user.id])].join(",")}),user_id.is.null`)
      .order("created_at", { ascending: false }).limit(Math.min(1000, limit * 5));
    if (error) throw new Error(`Activity log unavailable: ${error.message}`);
    const messages = (data ?? []).filter((message) => messageBelongsToBooks(message, keys, guard.user.id, selectedBook))
      .slice(0, limit).map((message) => {
        const payload = message.payload ?? {};
        const bookKey = message.user_id || payload.user_id || payload.book_id || payload.account_key;
        return { ...message, book_label: labels.get(String(bookKey ?? "")) ?? "Shared market report" };
      });
    return NextResponse.json({ messages });
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Agents service unreachable";
    return NextResponse.json({ messages: [], error: msg }, { status: 503 });
  }
}
