/**
 * Centralized environment configuration. Fail fast on missing required values.
 */
function required(name: string, fallback?: string): string {
  const v = process.env[name] ?? fallback;
  if (!v) {
    throw new Error(`Missing required env var: ${name}`);
  }
  return v;
}

export const config = {
  env: process.env.NODE_ENV ?? "development",
  port: process.env.PORT ?? "8000",
  corsOrigins: (process.env.CORS_ORIGINS ?? "http://localhost:3000")
    .split(",")
    .map((s) => s.trim()),
  supabase: {
    url: process.env.NEXT_PUBLIC_SUPABASE_URL ?? process.env.SUPABASE_URL ?? "",
    anonKey:
      process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ??
      process.env.SUPABASE_ANON_KEY ??
      "",
    serviceRoleKey: process.env.SUPABASE_SERVICE_ROLE_KEY ?? "",
    jwtSecret: process.env.SUPABASE_JWT_SECRET ?? ""
  },
  jwt: {
    secret: process.env.JWT_SECRET ?? "dev_only_change_me"
  },
  agents: {
    baseUrl: process.env.AGENTS_BASE_URL ?? "http://localhost:8001"
  }
};

// In non-test environments, warn (don't crash) on missing Supabase config so the
// API can boot during local Phase-0 verification before keys are filled in.
if (config.env !== "test") {
  if (!config.supabase.url || !config.supabase.anonKey) {
    // eslint-disable-next-line no-console
    console.warn(
      "[trezo-api] Supabase env not fully set — auth & profile routes will return 503"
    );
  }
}

export { required };
