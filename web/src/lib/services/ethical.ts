/**
 * Ethical filter service.
 *
 * Implements `TREZO_ETHICAL_FILTERS.md`:
 *  - Tier 1 = human rights violations / OFAC / forced labor.
 *      HARD BLOCK. Never overridable.
 *  - Tier 2 = discrimination / hate / EEOC class-action settlements.
 *      Default block. Overridable with reason.
 *  - Tier 3 = SEC fraud / FINRA bar / state AG predatory actions.
 *      Default block. Overridable with reason.
 *  - Tier 4 = user-toggleable categories (tobacco, weapons, etc.).
 *      Only blocks when the user has explicitly toggled that category on
 *      in their `ethical_filter_settings`.
 *
 * This module is server-only — it uses the service-role Supabase client.
 */

import { createClient as createServerSupabase } from "@/lib/supabase/server";
import { cacheGetOrSet } from "@/lib/cache";

export type FilterDecision =
  | { ok: true }
  | {
      ok: false;
      tier: 1 | 2 | 3 | 4;
      category: string;
      source: string;
      sourceUrl: string | null;
      evidence: string | null;
      overridable: boolean;
    };

export type EthicalSettings = {
  exclude_tobacco: boolean;
  exclude_weapons: boolean;
  exclude_fossil_fuels: boolean;
  exclude_private_prisons: boolean;
  exclude_gambling: boolean;
  exclude_predatory_lending: boolean;
  exclude_animal_testing: boolean;
  exclude_adult_entertainment: boolean;
  exclude_cannabis: boolean;
  exclude_crypto_mining: boolean;
};

const DEFAULT_SETTINGS: EthicalSettings = {
  exclude_tobacco: false,
  exclude_weapons: false,
  exclude_fossil_fuels: false,
  exclude_private_prisons: false,
  exclude_gambling: false,
  exclude_predatory_lending: false,
  exclude_animal_testing: false,
  exclude_adult_entertainment: false,
  exclude_cannabis: false,
  exclude_crypto_mining: false
};

// Map category name → which setting toggles it.
const CATEGORY_TO_SETTING: Record<string, keyof EthicalSettings> = {
  tobacco: "exclude_tobacco",
  weapons: "exclude_weapons",
  fossil_fuels: "exclude_fossil_fuels",
  private_prisons: "exclude_private_prisons",
  gambling: "exclude_gambling",
  predatory_lending: "exclude_predatory_lending",
  animal_testing: "exclude_animal_testing",
  adult_entertainment: "exclude_adult_entertainment",
  cannabis: "exclude_cannabis",
  crypto_mining: "exclude_crypto_mining"
};

type ExclusionRow = {
  ticker: string;
  category: string;
  tier: number;
  source: string;
  source_url: string | null;
  evidence: string | null;
};

/**
 * Look up all active exclusions for a ticker. Cached 10 minutes.
 */
async function getExclusionsForTicker(ticker: string): Promise<ExclusionRow[]> {
  const sym = ticker.toUpperCase();
  return cacheGetOrSet<ExclusionRow[]>(`ethical:ticker:${sym}`, 600, async () => {
    const supabase = createServerSupabase();
    const { data } = await supabase
      .from("ethical_exclusions")
      .select("ticker, category, tier, source, source_url, evidence")
      .eq("ticker", sym)
      .eq("active", true);
    return (data ?? []) as ExclusionRow[];
  });
}

/**
 * Read a user's filter settings (creating default row if none exists).
 */
export async function getUserSettings(userId: string): Promise<EthicalSettings> {
  const supabase = createServerSupabase();
  const { data } = await supabase
    .from("ethical_filter_settings")
    .select(
      "exclude_tobacco, exclude_weapons, exclude_fossil_fuels, exclude_private_prisons, exclude_gambling, exclude_predatory_lending, exclude_animal_testing, exclude_adult_entertainment, exclude_cannabis, exclude_crypto_mining"
    )
    .eq("user_id", userId)
    .maybeSingle();

  if (data) return data as EthicalSettings;

  // Seed defaults so future reads are cheap
  await supabase
    .from("ethical_filter_settings")
    .insert({ user_id: userId, ...DEFAULT_SETTINGS });
  return { ...DEFAULT_SETTINGS };
}

export async function updateUserSettings(
  userId: string,
  patch: Partial<EthicalSettings>
): Promise<EthicalSettings> {
  const supabase = createServerSupabase();
  const { data, error } = await supabase
    .from("ethical_filter_settings")
    .upsert(
      { user_id: userId, ...patch, updated_at: new Date().toISOString() },
      { onConflict: "user_id" }
    )
    .select(
      "exclude_tobacco, exclude_weapons, exclude_fossil_fuels, exclude_private_prisons, exclude_gambling, exclude_predatory_lending, exclude_animal_testing, exclude_adult_entertainment, exclude_cannabis, exclude_crypto_mining"
    )
    .single();
  if (error) throw error;
  return data as EthicalSettings;
}

/**
 * Returns a decision for whether `ticker` passes the filter for `userId`.
 */
export async function checkTicker(
  userId: string,
  ticker: string,
  settingsOverride?: EthicalSettings
): Promise<FilterDecision> {
  const exclusions = await getExclusionsForTicker(ticker);
  if (exclusions.length === 0) return { ok: true };

  const settings = settingsOverride ?? (await getUserSettings(userId));

  // Tier 1-3 always block (regardless of settings).
  const defaultBlock = exclusions.find((e) => e.tier >= 1 && e.tier <= 3);
  if (defaultBlock) {
    return {
      ok: false,
      tier: defaultBlock.tier as 1 | 2 | 3,
      category: defaultBlock.category,
      source: defaultBlock.source,
      sourceUrl: defaultBlock.source_url,
      evidence: defaultBlock.evidence,
      overridable: defaultBlock.tier !== 1
    };
  }

  // Tier 4 — only block if the user has toggled the category on.
  for (const e of exclusions) {
    if (e.tier !== 4) continue;
    const settingKey = CATEGORY_TO_SETTING[e.category];
    if (settingKey && settings[settingKey]) {
      return {
        ok: false,
        tier: 4,
        category: e.category,
        source: e.source,
        sourceUrl: e.source_url,
        evidence: e.evidence,
        overridable: true
      };
    }
  }

  return { ok: true };
}

/**
 * Log a user's override decision.
 */
export async function logOverride(
  userId: string,
  ticker: string,
  category: string,
  tier: number,
  reason: string
): Promise<void> {
  const supabase = createServerSupabase();
  await supabase.from("ethical_overrides").insert({
    user_id: userId,
    ticker: ticker.toUpperCase(),
    category,
    tier,
    reason
  });
}
