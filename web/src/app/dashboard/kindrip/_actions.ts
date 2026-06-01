"use server";

import { revalidatePath } from "next/cache";
import { createClient } from "@/lib/supabase/server";

function num(v: FormDataEntryValue | null, fallback = 0): number {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

export async function addChild(formData: FormData): Promise<void> {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) return;

  const name = String(formData.get("child_name") ?? "").trim();
  if (!name) return;
  const year = num(formData.get("birth_year"));
  const birthYear = year >= 2000 && year <= 2100 ? Math.round(year) : null;

  await supabase.from("kindrip_children").insert({
    user_id: user.id,
    child_name: name,
    birth_year: birthYear
  });
  revalidatePath("/dashboard/kindrip");
}

export async function saveChild(formData: FormData): Promise<void> {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) return;

  const childId = String(formData.get("child_id") ?? "");
  if (!childId) return;

  const mode = String(formData.get("contribution_mode") ?? "fixed");
  const cadence = String(formData.get("contribution_cadence") ?? "monthly");
  const allocMode = String(formData.get("allocation_mode") ?? "auto");

  // Allocation inputs arrive as percentages; store them as fractions.
  let schd = Math.max(0, num(formData.get("alloc_schd")));
  let vti = Math.max(0, num(formData.get("alloc_vti")));
  let bnd = Math.max(0, num(formData.get("alloc_bnd")));
  let cash = Math.max(0, num(formData.get("alloc_cash")));
  const sum = schd + vti + bnd + cash;
  if (sum > 0) {
    schd /= sum;
    vti /= sum;
    bnd /= sum;
    cash /= sum;
  } else {
    schd = 0.4;
    vti = 0.3;
    bnd = 0.2;
    cash = 0.1;
  }

  await supabase
    .from("kindrip_children")
    .update({
      contribution_mode: mode === "percent" ? "percent" : "fixed",
      contribution_value: Math.max(0, num(formData.get("contribution_value"), 25)),
      contribution_cadence: cadence === "weekly" ? "weekly" : "monthly",
      contribution_enabled: formData.get("contribution_enabled") === "on",
      allocation_mode: allocMode === "custom" ? "custom" : "auto",
      alloc_schd: Number(schd.toFixed(4)),
      alloc_vti: Number(vti.toFixed(4)),
      alloc_bnd: Number(bnd.toFixed(4)),
      alloc_cash: Number(cash.toFixed(4)),
      updated_at: new Date().toISOString()
    })
    .eq("id", childId)
    .eq("user_id", user.id);
  revalidatePath("/dashboard/kindrip");
}

export async function deleteChild(formData: FormData): Promise<void> {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) return;
  const childId = String(formData.get("child_id") ?? "");
  if (!childId) return;
  await supabase
    .from("kindrip_children")
    .delete()
    .eq("id", childId)
    .eq("user_id", user.id);
  revalidatePath("/dashboard/kindrip");
}
