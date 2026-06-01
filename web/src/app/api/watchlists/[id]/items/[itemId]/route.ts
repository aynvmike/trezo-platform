import { NextResponse } from "next/server";
import { z } from "zod";
import { createClient } from "@/lib/supabase/server";
import { removeItem, updateItem, reorderItem } from "@/lib/watchlists";

export const dynamic = "force-dynamic";

async function requireUser() {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  return user;
}

const patchSchema = z.object({
  notes: z.string().max(500).optional(),
  starred: z.boolean().optional(),
  reorder: z.enum(["up", "down"]).optional()
});

export async function PATCH(
  request: Request,
  { params }: { params: { id: string; itemId: string } }
) {
  const user = await requireUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  try {
    const body = patchSchema.parse(await request.json());
    if (body.reorder) {
      await reorderItem(user.id, params.id, params.itemId, body.reorder);
    }
    if (typeof body.notes !== "undefined" || typeof body.starred !== "undefined") {
      await updateItem(user.id, params.itemId, {
        notes: body.notes,
        starred: body.starred
      });
    }
    return NextResponse.json({ ok: true });
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Invalid request";
    return NextResponse.json({ error: msg }, { status: 400 });
  }
}

export async function DELETE(
  _request: Request,
  { params }: { params: { id: string; itemId: string } }
) {
  const user = await requireUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  await removeItem(user.id, params.itemId);
  return NextResponse.json({ ok: true });
}
