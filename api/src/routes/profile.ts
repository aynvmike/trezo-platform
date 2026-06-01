import { Router } from "express";
import { z } from "zod";
import { requireAuth, type AuthedRequest } from "../middleware/auth";
import { supabaseAdmin } from "../core/supabase";

export const profileRouter = Router();

const profileSchema = z.object({
  display_name: z.string().min(1).max(80).optional(),
  stock_capital_usd: z.number().nonnegative().optional(),
  crypto_capital_usd: z.number().nonnegative().optional(),
  options_capital_usd: z.number().nonnegative().optional(),
  risk_tolerance: z.enum(["conservative", "balanced", "aggressive"]).optional(),
  daily_profit_target_usd: z.number().nonnegative().optional(),
  tax_filing_status: z
    .enum(["single", "married_joint", "married_separate", "head_of_household"])
    .optional(),
  onboarding_complete: z.boolean().optional()
});

profileRouter.get("/", requireAuth, async (req: AuthedRequest, res, next) => {
  try {
    const { data, error } = await supabaseAdmin()
      .from("profiles")
      .select("*")
      .eq("user_id", req.user!.id)
      .maybeSingle();
    if (error) throw error;
    res.json({ profile: data });
  } catch (e) {
    next(e);
  }
});

profileRouter.put("/", requireAuth, async (req: AuthedRequest, res, next) => {
  try {
    const parsed = profileSchema.parse(req.body);
    const { data, error } = await supabaseAdmin()
      .from("profiles")
      .upsert(
        { user_id: req.user!.id, ...parsed, updated_at: new Date().toISOString() },
        { onConflict: "user_id" }
      )
      .select()
      .single();
    if (error) throw error;
    res.json({ profile: data });
  } catch (e) {
    next(e);
  }
});
