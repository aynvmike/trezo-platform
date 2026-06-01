import { NextResponse } from "next/server";
import { z } from "zod";
import { createClient } from "@/lib/supabase/server";
import { renameWatchlist, deleteWatchlist, getWatchlist } from "@/lib/watchlists";

export const dynamic = "force-dynamic";

async function requireUser() {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  return user;
}

export async function GET(_req: Request, { params }: { params: { id: string } }) {
  const user = await requireUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  const wl = await getWatchlist(user.id, params.id);
  if (!wl) return NextResponse.json({ error: "Not found" }, { status: 404 });
  return NextResponse.json(wl);
}

const patchSchema = z.object({ name: z.string().min(1).max(80) });

export async function PATCH(request: Request, { params }: { params: { id: string } }) {
  const user = await requireUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  try {
    const body = patchSchema.parse(await request.json());
    await renameWatchlist(user.id, params.id, body.name);
    return NextResponse.json({ ok: true });
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Invalid request";
    return NextResponse.json({ error: msg }, { status: 400 });
  }
}

export async function DELETE(_req: Request, { params }: { params: { id: string } }) {
  const user = await requireUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  await deleteWatchlist(user.id, params.id);
  return NextResponse.json({ ok: true });
}
