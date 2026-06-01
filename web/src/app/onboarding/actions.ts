"use server";

import { redirect } from "next/navigation";
import { z } from "zod";
import { createClient } from "@/lib/supabase/server";

const profileSchema = z.object({
  display_name: z.string().min(1).max(80),
  stock_capital_usd: z.coerce.number().nonnegative(),
  crypto_capital_usd: z.coerce.number().nonnegative(),
  options_capital_usd: z.coerce.number().nonnegative(),
  risk_tolerance: z.enum(["conservative", "balanced", "aggressive"]),
  daily_profit_target_usd: z.coerce.number().nonnegative(),
  tax_filing_status: z.enum([
    "single",
    "married_joint",
    "married_separate",
    "head_of_household"
  ]),
  // Tax-strategy fields — optional; blank inputs coerce to 0 and are skipped
  // by the Tax Optimizer until the user fills them in.
  annual_income_usd: z.coerce.number().nonnegative().default(0),
  retirement_contribution_pct: z.coerce.number().min(0).max(100).default(0),
  employer_match_pct: z.coerce.number().min(0).max(200).default(0),
  employer_match_cap_pct: z.coerce.number().min(0).max(100).default(0)
});

export type ProfileFormState = {
  ok: boolean;
  error?: string;
  fieldErrors?: Record<string, string[]>;
};

export async function saveProfile(
  _prev: ProfileFormState,
  formData: FormData
): Promise<ProfileFormState> {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) {
    return { ok: false, error: "Not signed in." };
  }

  const raw = Object.fromEntries(formData.entries());
  const parsed = profileSchema.safeParse(raw);
  if (!parsed.success) {
    return {
      ok: false,
      error: "Please double-check the highlighted fields.",
      fieldErrors: parsed.error.flatten().fieldErrors as Record<string, string[]>
    };
  }

  const { error } = await supabase
    .from("profiles")
    .upsert(
      {
        user_id: user.id,
        ...parsed.data,
        onboarding_complete: true,
        updated_at: new Date().toISOString()
      },
      { onConflict: "user_id" }
    );

  if (error) {
    return { ok: false, error: error.message };
  }

  redirect("/dashboard");
}
