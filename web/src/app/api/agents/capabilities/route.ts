import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { requireUser } from "@/lib/auth-guards";
import type { BookCapabilities, CapabilitiesResponse } from "@/lib/agent-capabilities";

export const dynamic = "force-dynamic";
const AGENTS_BASE = process.env.AGENTS_BASE_URL ?? "http://localhost:8001";

export async function GET() {
  const supabase = createClient();
  const guard = await requireUser(supabase);
  if (!guard.ok) return guard.response;
  const { data, error } = await supabase.from("trading_accounts")
    .select("account_key, label").eq("owner_id", guard.user.id).order("label");
  if (error) return NextResponse.json({ books: [], error: `Unable to load your accounts: ${error.message}` }, { status: 503 });
  const owned = new Map((data ?? []).map((row) => [String(row.account_key), String(row.label ?? "Account")]));
  if (!owned.size) return NextResponse.json({ books: [] });
  try {
    const response = await fetch(`${AGENTS_BASE}/agents/capabilities`, {
      cache: "no-store", signal: AbortSignal.timeout(15000),
    });
    const body = await response.json() as CapabilitiesResponse & { configuration_notes?: unknown[] };
    if (!response.ok || !Array.isArray(body.books)) {
      throw new Error(body.error || `Capability service returned ${response.status}`);
    }
    const warnings: string[] = [];
    if (body.error) warnings.push("The trading service could not fully verify its account directory. Availability may be incomplete.");
    if (Array.isArray(body.configuration_notes) && body.configuration_notes.length) {
      // Account validation diagnostics are service-wide and may describe
      // another owner's configuration; expose only the presence of a problem.
      warnings.push("Some runtime account configurations need attention.");
    }
    // Return only the documented public fields and the caller's books.
    const books: BookCapabilities[] = [...owned].map(([bookId, label]) => {
      const match = body.books?.find((book) => book.book_id === bookId);
      return { book_id: bookId, label, note: typeof match?.note === "string" ? match.note : undefined, capabilities: Array.isArray(match?.capabilities)
        ? match.capabilities.map(({ id, label: laneLabel, status, reason, directions }) => ({
          id, label: laneLabel, status, reason, directions: Array.isArray(directions) ? directions : [],
        }))
        : [{ id: "book_runtime", label: "Account availability", status: "unverified", reason: "This account was not returned by the trading service. Its capabilities have not been verified.", directions: [] }],
      };
    });
    return NextResponse.json({ books, warnings, generated_at: body.generated_at });
  } catch (error) {
    return NextResponse.json({ books: [], error: error instanceof Error ? error.message : "Unable to verify trading capabilities." }, { status: 503 });
  }
}
