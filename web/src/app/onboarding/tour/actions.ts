"use server";

import { createClient } from "@/lib/supabase/server";

/**
 * PAGES-04: the wizard used to collect broker / paper-live mode / active
 * layers too, and silently dropped all three. Only the daily loss cap
 * maps to a real column, so only it is accepted here. Broker connect
 * lives on Settings → Connections; trading mode is paper (the live
 * executor does not exist); layers are switched on in Bot Tuning.
 */
export type TourConfig = {
  dailyRiskLimit: number;
};

/**
 * Persists the daily loss cap to profiles.daily_loss_limit_usd — the
 * same value the Trading page and Risk Manager read. Best-effort: never
 * throws into the wizard, but a failed write is reported as ok:false
 * (and logged) rather than swallowed.
 */
export async function saveTourSettings(config: TourConfig): Promise<{ ok: boolean }> {
  try {
    const supabase = createClient();
    const {
      data: { user },
    } = await supabase.auth.getUser();
    if (!user) return { ok: false };
    const limit = Math.max(0, Math.round(Number(config.dailyRiskLimit) || 0));
    const { error } = await supabase
      .from("profiles")
      .update({ daily_loss_limit_usd: limit })
      .eq("user_id", user.id);
    if (error) {
      console.error(`[onboarding/tour] profiles update failed: ${error.message}`);
      return { ok: false };
    }
    return { ok: true };
  } catch {
    return { ok: false };
  }
}
