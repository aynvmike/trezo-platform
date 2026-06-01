"use server";

import { revalidatePath } from "next/cache";
import { z } from "zod";
import { createClient } from "@/lib/supabase/server";

const schema = z.object({
  tcs_threshold: z.coerce.number().int().min(300).max(1000),
  max_open_positions: z.coerce.number().int().min(1).max(20),
  consecutive_loss_limit: z.coerce.number().int().min(2).max(10),
  risk_per_trade_pct: z.coerce.number().min(0.005).max(0.25),
  default_stop_pct: z.coerce.number().min(0.01).max(0.5),
  default_target_pct: z.coerce.number().min(0.01).max(1.0),
  pattern_enabled: z.coerce.boolean(),
  stms_enabled: z.coerce.boolean(),
  extended_enabled: z.coerce.boolean(),
  crypto_enabled: z.coerce.boolean(),
  autonomy_mode: z.enum(["suggest", "guarded", "full"]),
  account_posture: z.enum(["auto", "growth", "balanced", "income"]),
  risk_profile: z.enum(["conservative", "balanced", "aggressive", "expert"]),
  min_reward_risk: z.coerce.number().min(0.3).max(3.0),
  switching_mode: z.enum(["off", "fixed", "adaptive", "tiered"]),
  switching_advantage_pct: z.coerce.number().int().min(0).max(50),
  wheel_auto_execute: z.coerce.boolean(),
  expert_mode_enabled: z.coerce.boolean(),
  terse_format_enabled: z.coerce.boolean(),
  auto_trade_enabled: z.coerce.boolean()
});

export type BotFormState = { ok: boolean; message?: string };

const MARKET_TYPES = ["crypto", "stocks", "options", "income"] as const;

function readOverride(formData: FormData, key: string): number | null {
  const raw = formData.get(key);
  if (raw === null || String(raw).trim() === "") return null;
  const n = Number(raw);
  return Number.isFinite(n) && n > 0 ? Math.round(n) : null;
}

export async function saveBotSettings(
  _prev: BotFormState,
  formData: FormData
): Promise<BotFormState> {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) return { ok: false, message: "Not signed in." };

  const raw = {
    tcs_threshold: formData.get("tcs_threshold"),
    max_open_positions: formData.get("max_open_positions"),
    consecutive_loss_limit: formData.get("consecutive_loss_limit"),
    risk_per_trade_pct: formData.get("risk_per_trade_pct"),
    default_stop_pct: formData.get("default_stop_pct"),
    default_target_pct: formData.get("default_target_pct"),
    pattern_enabled: formData.get("pattern_enabled") === "on",
    stms_enabled: formData.get("stms_enabled") === "on",
    extended_enabled: formData.get("extended_enabled") === "on",
    crypto_enabled: formData.get("crypto_enabled") === "on",
    autonomy_mode: formData.get("autonomy_mode") ?? "guarded",
    account_posture: formData.get("account_posture") ?? "auto",
    risk_profile: formData.get("risk_profile") ?? "balanced",
    min_reward_risk: formData.get("min_reward_risk") ?? 1.5,
    switching_mode: formData.get("switching_mode") ?? "adaptive",
    switching_advantage_pct: formData.get("switching_advantage_pct") ?? 10,
    wheel_auto_execute: formData.get("wheel_auto_execute") === "on",
    expert_mode_enabled: formData.get("expert_mode_enabled") === "on",
    terse_format_enabled: formData.get("terse_format_enabled") === "on",
    auto_trade_enabled: formData.get("auto_trade_enabled") === "on"
  };

  const parsed = schema.safeParse(raw);
  if (!parsed.success) {
    return { ok: false, message: "Some values were out of range - not saved." };
  }

  const allocation_overrides: Record<string, number> = {};
  for (const mt of MARKET_TYPES) {
    const v = readOverride(formData, `alloc_${mt}`);
    if (v !== null) allocation_overrides[mt] = v;
  }

  const PW_KEYS = [
    "trend", "momentum", "macd", "volume", "breakout",
    "candle_pattern", "bb_position", "vwap_alignment",
    "market_alignment", "iv_environment"
  ] as const;
  const pattern_weights: Record<string, number> = {};
  let pwAnyCustom = false;
  const DEFAULTS: Record<string, number> = {
    trend: 12, momentum: 10, macd: 12, volume: 10, breakout: 12,
    candle_pattern: 10, bb_position: 8, vwap_alignment: 8,
    market_alignment: 8, iv_environment: 10
  };
  for (const k of PW_KEYS) {
    const rawPw = formData.get(`pw_${k}`);
    if (rawPw === null || String(rawPw).trim() === "") continue;
    let n = Math.round(Number(rawPw));
    if (!Number.isFinite(n)) continue;
    if (n < 0) n = 0;
    if (n > 30) n = 30;
    pattern_weights[k] = n;
    if (n !== DEFAULTS[k]) pwAnyCustom = true;
  }
  const pwSave = pwAnyCustom ? pattern_weights : null;

  try {
    const { data: prev } = await supabase
      .from("bot_settings")
      .select("risk_profile, min_reward_risk, default_stop_pct, default_target_pct, risk_per_trade_pct")
      .eq("user_id", user.id)
      .maybeSingle();
    const changed =
      !prev ||
      prev.risk_profile !== parsed.data.risk_profile ||
      Number(prev.min_reward_risk) !== Number(parsed.data.min_reward_risk) ||
      Number(prev.default_stop_pct) !== Number(parsed.data.default_stop_pct) ||
      Number(prev.default_target_pct) !== Number(parsed.data.default_target_pct) ||
      Number(prev.risk_per_trade_pct) !== Number(parsed.data.risk_per_trade_pct);
    if (changed) {
      await supabase.from("risk_profile_audit").insert({
        user_id: user.id,
        from_profile: prev?.risk_profile ?? null,
        to_profile: parsed.data.risk_profile,
        from_rr: prev?.min_reward_risk ?? null,
        to_rr: parsed.data.min_reward_risk,
        from_stop_pct: prev?.default_stop_pct ?? null,
        to_stop_pct: parsed.data.default_stop_pct,
        from_target_pct: prev?.default_target_pct ?? null,
        to_target_pct: parsed.data.default_target_pct,
        from_risk_pct: prev?.risk_per_trade_pct ?? null,
        to_risk_pct: parsed.data.risk_per_trade_pct,
        note:
          parsed.data.risk_profile === "expert"
            ? "User entered Expert mode - accepts responsibility for raw values."
            : prev?.risk_profile === "expert"
            ? "User exited Expert mode - back on preset."
            : "Preset adjustment."
      });
    }
  } catch {
    // Migration 0027 may not be applied; never block the save.
  }

  const { error } = await supabase
    .from("bot_settings")
    .upsert(
      {
        user_id: user.id,
        ...parsed.data,
        allocation_overrides,
        pattern_weights: pwSave,
        updated_at: new Date().toISOString()
      },
      { onConflict: "user_id" }
    );

  if (error) return { ok: false, message: error.message };

  revalidatePath("/dashboard/settings/bot");
  return { ok: true, message: "Saved. Agents pick up the new values within 30 seconds." };
}
