"use server";

import { revalidatePath } from "next/cache";
import { z } from "zod";
import { createClient } from "@/lib/supabase/server";

const schema = z.object({
  display_name: z.string().min(1).max(80),
  stock_capital_usd: z.coerce.number().nonnegative(),
  crypto_capital_usd: z.coerce.number().nonnegative(),
  options_capital_usd: z.coerce.number().nonnegative(),
  risk_tolerance: z.enum(["conservative", "balanced", "aggressive"]),
  daily_profit_target_usd: z.coerce.number().nonnegative(),
  daily_loss_limit_usd: z.coerce.number().nonnegative(),
  tax_filing_status: z.enum([
    "single",
    "married_joint",
    "married_separate",
    "head_of_household"
  ]),
  // Tax-strategy fields — power the Tax Optimizer's strategy section.
  annual_income_usd: z.coerce.number().nonnegative(),
  state_tax_rate_pct: z.coerce.number().min(0).max(20),
  retirement_contribution_pct: z.coerce.number().min(0).max(100),
  employer_match_pct: z.coerce.number().min(0).max(200),
  employer_match_cap_pct: z.coerce.number().min(0).max(100),
  withholding_set_aside_pct: z.coerce.number().min(0).max(100)
});

export type ProfileFormState = {
  ok: boolean;
  message?: string;
  fieldErrors?: Record<string, string[]>;
};

export async function saveProfileSettings(
  _prev: ProfileFormState,
  formData: FormData
): Promise<ProfileFormState> {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) return { ok: false, message: "Not signed in." };

  const parsed = schema.safeParse(Object.fromEntries(formData.entries()));
  if (!parsed.success) {
    return {
      ok: false,
      message: "Some fields need attention.",
      fieldErrors: parsed.error.flatten().fieldErrors as Record<string, string[]>
    };
  }

  // Use upsert (not update) so the save works even if no profile row
  // exists yet for this user. The `update().eq(...)` pattern silently
  // returns OK with zero rows touched if the row is missing - the
  // user thinks they saved but nothing landed. Mike caught this
  // 2026-06-04 when his $750 / $1000 settings didn't propagate.
  const { error } = await supabase
    .from("profiles")
    .upsert(
      {
        user_id: user.id,
        ...parsed.data,
        updated_at: new Date().toISOString()
      },
      { onConflict: "user_id" }
    );

  if (error) {
    return { ok: false, message: error.message };
  }

  revalidatePath("/dashboard/settings/profile");
  revalidatePath("/dashboard/paper");
  revalidatePath("/dashboard/tax");
  revalidatePath("/dashboard");
  return { ok: true, message: "Saved." };
}
