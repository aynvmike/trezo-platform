/**
 * Service-role Supabase client — SERVER ONLY.
 *
 * AUTH-01 / AUTH-02 / OAUTH-1: the machine-to-machine routes
 * (/api/internal/broker-token, /api/cron/refresh-broker-tokens) authenticate
 * with a shared secret, not a user session. The cookie-based client in
 * ./server.ts runs as the ANON role with no session, so RLS on
 * broker_connections returned zero rows and the whole per-user OAuth path
 * was dead. This client bypasses RLS using SUPABASE_SERVICE_ROLE_KEY.
 *
 * Rules:
 *  - Import ONLY from route handlers / server code that has already
 *    verified a machine secret. Never from client components, never from a
 *    route that serves a browser session (use ./server.ts there so RLS
 *    keeps doing the per-user scoping).
 *  - Never log the key value. The env key NAME is fine.
 */

import {
  createClient as createSupabaseClient,
  type SupabaseClient
} from "@supabase/supabase-js";

export const SERVICE_ROLE_KEY_ENV = "SUPABASE_SERVICE_ROLE_KEY";

export function isServiceRoleConfigured(): boolean {
  return Boolean(process.env[SERVICE_ROLE_KEY_ENV]);
}

/**
 * Build a service-role client. Throws (does not silently fall back to anon)
 * when the key or URL is missing, so a misconfigured server fails loudly
 * instead of returning "no active connection" for every user.
 */
export function createAdminClient(): SupabaseClient {
  if (typeof window !== "undefined") {
    throw new Error("createAdminClient() is server-only and must never run in the browser.");
  }
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env[SERVICE_ROLE_KEY_ENV];
  if (!url) {
    throw new Error("NEXT_PUBLIC_SUPABASE_URL is not set on the web service.");
  }
  if (!key) {
    throw new Error(
      `${SERVICE_ROLE_KEY_ENV} is not set on the web service — machine-to-machine routes cannot read broker_connections (RLS blocks the anon role).`
    );
  }
  return createSupabaseClient(url, key, {
    auth: {
      persistSession: false,
      autoRefreshToken: false,
      detectSessionInUrl: false
    }
  });
}
