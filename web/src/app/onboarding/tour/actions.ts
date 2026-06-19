"use server";

import { createClient } from "@/lib/supabase/server";

export type TourConfig = {
  broker: string;
  mode: "paper" | "live";
  activeLayers: number[];
  dailyRiskLimit: number;
};

/**
 * Persists what maps cleanly to a known column today: the daily loss cap
 * (profiles.daily_loss_limit_usd — the same value the Trading page + Risk
 * Manager read). Broker connect lives on the Connections page; paper/live
 * routing stays env-gated (Phase 10b); per-layer enablement is informational
 * here. Best-effort: never throws into the wizard.
 */
export async function saveTourSettings(config: TourConfig): Promise<{ ok: boolean }> {
  try {
    const supabase = createClient();
    const {
      data: { user },
    } = await supabase.auth.getUser();
    if (!user) return { ok: false };
    const limit = Math.max(0, Math.round(Number(config.dailyRiskLimit) || 0));
    await supabase.from("profiles").update({ daily_loss_limit_usd: limit }).eq("user_id", user.id);
    return { ok: true };
  } catch {
    return { ok: false };
  }
}
