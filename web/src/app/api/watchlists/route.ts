import { NextResponse } from "next/server";
import { z } from "zod";
import { createClient } from "@/lib/supabase/server";
import { listWatchlists, createWatchlist } from "@/lib/watchlists";

export const dynamic = "force-dynamic";

async function requireUser() {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  return user;
}

export async function GET() {
  const user = await requireUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const lists = await listWatchlists(user.id);
  return NextResponse.json({ watchlists: lists });
}

const createSchema = z.object({ name: z.string().min(1).max(80) });

export async function POST(request: Request) {
  const user = await requireUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  try {
    const body = createSchema.parse(await request.json());
    const list = await createWatchlist(user.id, body.name);
    return NextResponse.json({ watchlist: list }, { status: 201 });
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Invalid request";
    return NextResponse.json({ error: msg }, { status: 400 });
  }
}
