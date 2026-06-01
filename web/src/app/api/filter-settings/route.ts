import { NextResponse } from "next/server";
import { z } from "zod";
import { createClient } from "@/lib/supabase/server";
import { getUserSettings, updateUserSettings } from "@/lib/services/ethical";

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
  const settings = await getUserSettings(user.id);
  return NextResponse.json({ settings });
}

const patchSchema = z.object({
  exclude_tobacco: z.boolean().optional(),
  exclude_weapons: z.boolean().optional(),
  exclude_fossil_fuels: z.boolean().optional(),
  exclude_private_prisons: z.boolean().optional(),
  exclude_gambling: z.boolean().optional(),
  exclude_predatory_lending: z.boolean().optional(),
  exclude_animal_testing: z.boolean().optional(),
  exclude_adult_entertainment: z.boolean().optional(),
  exclude_cannabis: z.boolean().optional(),
  exclude_crypto_mining: z.boolean().optional()
});

export async function PATCH(request: Request) {
  const user = await requireUser();
  if (!user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  try {
    const body = patchSchema.parse(await request.json());
    const settings = await updateUserSettings(user.id, body);
    return NextResponse.json({ settings });
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Invalid request";
    return NextResponse.json({ error: msg }, { status: 400 });
  }
}
