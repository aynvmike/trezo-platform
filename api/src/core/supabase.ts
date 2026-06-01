import { createClient, SupabaseClient } from "@supabase/supabase-js";
import { config } from "./config";

let _admin: SupabaseClient | null = null;

/**
 * Service-role Supabase client for the API. Never expose to the browser.
 * Used for trusted operations (profile upserts, agent logs).
 */
export function supabaseAdmin(): SupabaseClient {
  if (_admin) return _admin;
  if (!config.supabase.url || !config.supabase.serviceRoleKey) {
    throw new Error("Supabase service-role credentials not configured");
  }
  _admin = createClient(config.supabase.url, config.supabase.serviceRoleKey, {
    auth: { persistSession: false, autoRefreshToken: false }
  });
  return _admin;
}
