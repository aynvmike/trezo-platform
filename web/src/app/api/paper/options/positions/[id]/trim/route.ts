import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { getOwnerBookKeys, bookQueryKeys } from "@/lib/books";

export const dynamic = "force-dynamic";

const AGENTS_BASE = process.env.AGENTS_BASE_URL ?? "http://localhost:8001";

/**
 * POST /api/paper/options/positions/[id]/trim
 *
 * Body: { contracts_to_close: number, reason?: string }
 *
 * Calls the agents-side options trim primitive which:
 *  - decrements the open options_positions row's `contracts`,
 *  - inserts a closed_manual row for the closed slice,
 *  - writes a trade_outcomes partial-exit row,
 *  - logs to Mem0.
 *
 * V1 is modeled-close only - if a live Alpaca order was placed, the
 * user is expected to mirror the close manually until V2 ships
 * automatic sell-to-close.
 *
 * Task #29, 2026-06-02.
 */
export async function POST(
  request: Request,
  { params }: { params: { id: string } }
) {
  const supabase = createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ ok: false, error: "Not signed in." }, { status: 401 });
  }

  let body: { contracts_to_close?: number; reason?: string } = {};
  try {
    body = (await request.json()) as { contracts_to_close?: number; reason?: string };
  } catch {
    try {
      const form = await request.formData();
      body = {
        contracts_to_close: Number(form.get("contracts_to_close") ?? 1),
        reason: String(form.get("reason") ?? "user_trim"),
      };
    } catch {
      body = {};
    }
  }

  const contracts = Math.max(1, Math.floor(Number(body.contracts_to_close ?? 1)));
  const reason = body.reason ?? "user_trim";

  // Confirm the position sits in one of this person's BOOKS before
  // invoking (rv:web-pages sweep: user_id is the book key since 0047). A
  // failed read is a 500, not a 404.
  const books = await getOwnerBookKeys(supabase, user.id);
  if (books.failure) {
    return NextResponse.json({ ok: false, error: `Could not resolve your books: ${books.failure.message}` }, { status: 500 });
  }
  const { data: pos, error: posErr } = await supabase
    .from("options_positions")
    .select("id, user_id, underlying, status, contracts")
    .eq("id", params.id)
    .in("user_id", bookQueryKeys(books.data))
    .maybeSingle();
  if (posErr) {
    return NextResponse.json({ ok: false, error: `Position read failed: ${posErr.message}` }, { status: 500 });
  }
  if (!pos) {
    return NextResponse.json({ ok: false, error: "Options position not found" }, { status: 404 });
  }
  if (pos.status !== "open") {
    return NextResponse.json({ ok: false, error: "Position is not open" }, { status: 409 });
  }

  try {
    const r = await fetch(`${AGENTS_BASE}/paper/options/trim`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        // The BOOK that holds the position, not the person: the agents
        // bind the broker account by this id.
        user_id: pos.user_id,
        position_id: params.id,
        contracts_to_close: contracts,
        reason,
      }),
      signal: AbortSignal.timeout(15_000),
    });
    const data = await r.json();
    return NextResponse.json(data, { status: r.ok ? 200 : r.status });
  } catch (e) {
    return NextResponse.json(
      { ok: false, error: e instanceof Error ? e.message : "Network error" },
      { status: 502 }
    );
  }
}
