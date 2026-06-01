"use server";

import { revalidatePath } from "next/cache";
import { createClient } from "@/lib/supabase/server";

export type HoldingResult = { ok: boolean; error?: string };

async function fetchCompanyName(ticker: string): Promise<string | null> {
  // Best-effort enrichment: ask Finnhub for the company name so any
  // ticker the user adds (not just library ETFs) gets a readable label.
  // Silent failure — enrichment is icing, not blocking.
  const key = process.env.FINNHUB_API_KEY;
  if (!key) return null;
  try {
    const r = await fetch(
      `https://finnhub.io/api/v1/stock/profile2?symbol=${encodeURIComponent(ticker)}&token=${key}`,
      { cache: "no-store", signal: AbortSignal.timeout(8000) }
    );
    if (!r.ok) return null;
    const j = (await r.json()) as { name?: string };
    return j && typeof j.name === "string" && j.name.trim() ? j.name.trim() : null;
  } catch {
    return null;
  }
}

/**
 * Add a dividend-layer holding (a library ETF or any dividend ticker).
 * Accepts an optional `name` form field — when added from the library
 * we pass the curated name; for custom adds we ask Finnhub for the
 * company name so the holding card reads well.
 */
export async function addHolding(formData: FormData): Promise<void> {
  const ticker = String(formData.get("ticker") ?? "").trim().toUpperCase();
  if (!ticker || !/^[A-Z][A-Z0-9.-]{0,9}$/.test(ticker)) return;

  let shares = Number(formData.get("shares") ?? 0);
  if (!Number.isFinite(shares) || shares < 0) shares = 0;
  let yieldPct = Number(formData.get("dist_yield_pct") ?? 0);
  if (!Number.isFinite(yieldPct) || yieldPct < 0) yieldPct = 0;
  if (yieldPct > 500) yieldPct = 500;

  // Library Add passes a name; custom Add does not — fetch then.
  let name = String(formData.get("name") ?? "").trim();
  if (!name) {
    name = (await fetchCompanyName(ticker)) ?? "";
  }

  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) return;

  await supabase.from("user_positions").upsert(
    {
      user_id: user.id,
      ticker,
      asset_type: "yieldmax",
      shares,
      dist_yield_pct: yieldPct,
      drip_enabled: true,
      notes: name || null
    },
    { onConflict: "user_id,ticker,asset_type", ignoreDuplicates: true }
  );
  revalidatePath("/dashboard/yieldmax");
  revalidatePath("/dashboard/watchlists");
}

/** Remove a dividend-layer holding. Returns a result so the UI can react. */
export async function removeHolding(formData: FormData): Promise<HoldingResult> {
  const id = String(formData.get("position_id") ?? "").trim();
  if (!id) return { ok: false, error: "Missing holding id." };

  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) return { ok: false, error: "Not signed in." };

  const { error } = await supabase
    .from("user_positions")
    .delete()
    .eq("id", id)
    .eq("user_id", user.id);
  if (error) return { ok: false, error: error.message };

  revalidatePath("/dashboard/yieldmax");
  return { ok: true };
}

/** Save one holding's share count, DRIP setting, and distribution yield. */
export async function saveHolding(formData: FormData): Promise<HoldingResult> {
  const positionId = String(formData.get("position_id") ?? "").trim();
  if (!positionId) return { ok: false, error: "Missing holding id." };

  let shares = Number(formData.get("shares") ?? 0);
  if (!Number.isFinite(shares) || shares < 0) shares = 0;
  const dripEnabled =
    formData.get("drip_enabled") === "on" || formData.get("drip_enabled") === "true";
  let yieldPct = Number(formData.get("dist_yield_pct") ?? 0);
  if (!Number.isFinite(yieldPct) || yieldPct < 0) yieldPct = 0;
  if (yieldPct > 500) yieldPct = 500;

  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) return { ok: false, error: "Not signed in." };

  const { error } = await supabase
    .from("user_positions")
    .update({ shares, drip_enabled: dripEnabled, dist_yield_pct: yieldPct })
    .eq("id", positionId)
    .eq("user_id", user.id);
  if (error) return { ok: false, error: error.message };

  revalidatePath("/dashboard/yieldmax");
  return { ok: true };
}
