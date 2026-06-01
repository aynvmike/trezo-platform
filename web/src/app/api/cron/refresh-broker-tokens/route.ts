import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { decryptToken, encryptToken } from "@/lib/broker-connections";

export const dynamic = "force-dynamic";

/**
 * POST /api/cron/refresh-broker-tokens
 *
 * Scheduled OAuth refresh — finds every broker_connections row whose
 * access_token expires in the next hour, calls that broker's refresh
 * endpoint, writes the new token + new expiry back, and appends an
 * audit row to `broker_token_refresh_log`.
 *
 * Broker-agnostic: the per-broker refresh logic lives in REFRESHERS so
 * adding Webull / Robinhood is a single new entry, no other changes.
 *
 * Failure handling — `consecutive_refresh_failures` on the connection
 * row increments on every failed attempt and resets to 0 on success.
 * Once it hits MAX_FAILURES the row is flipped to status='expired' so
 * the dashboard can prompt the user to reconnect (a stale loop of bad
 * tokens never reaches the broker).
 *
 * Auth: requires `Bearer ${CRON_SECRET}` header so external schedulers
 * (the agents service, Vercel Cron, a Windows Task Scheduler curl)
 * can hit it without a user session. CRON_SECRET lives in web/.env.local.
 */
const HORIZON_MS = 60 * 60 * 1000; // refresh anything expiring in <1h
const MAX_FAILURES = 3;

export async function POST(request: Request) {
  // Auth gate
  const secret = process.env.CRON_SECRET;
  const auth = request.headers.get("authorization") || "";
  if (!secret) {
    return NextResponse.json(
      { ok: false, error: "CRON_SECRET not configured." },
      { status: 500 }
    );
  }
  if (auth !== `Bearer ${secret}`) {
    return NextResponse.json({ ok: false, error: "Unauthorized." }, { status: 401 });
  }

  const supabase = createClient();
  const horizon = new Date(Date.now() + HORIZON_MS).toISOString();
  const { data: rows, error } = await supabase
    .from("broker_connections")
    .select(
      "id, user_id, broker, refresh_token_enc, expires_at, status, consecutive_refresh_failures"
    )
    .eq("status", "active")
    .lte("expires_at", horizon)
    .not("refresh_token_enc", "is", null);

  if (error) {
    return NextResponse.json({ ok: false, error: error.message }, { status: 500 });
  }

  const results: {
    id: string;
    broker: string;
    status: AuditStatus;
    note: string;
  }[] = [];

  for (const row of rows ?? []) {
    const fn = REFRESHERS[row.broker as keyof typeof REFRESHERS];
    const ranAt = new Date().toISOString();

    if (!fn) {
      results.push({
        id: row.id,
        broker: row.broker,
        status: "no_refresher",
        note: `No refresher registered for ${row.broker}`,
      });
      await logAttempt(supabase, row, "no_refresher",
        `No refresher registered for ${row.broker}`, null, ranAt);
      continue;
    }

    let plaintextRefresh: string;
    try {
      plaintextRefresh = decryptToken(row.refresh_token_enc as string);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "decrypt failed";
      results.push({ id: row.id, broker: row.broker, status: "malformed", note: msg });
      await logAttempt(supabase, row, "malformed", msg, null, ranAt);
      await bumpFailure(supabase, row, ranAt);
      continue;
    }

    try {
      const out = await fn(plaintextRefresh);
      if (!out) {
        results.push({
          id: row.id,
          broker: row.broker,
          status: "skipped",
          note: "Refresher returned null (broker may not issue expiring tokens)",
        });
        await logAttempt(supabase, row, "skipped",
          "Refresher returned null", null, ranAt);
        // Not a failure — reset the counter so we don't expire valid rows.
        await supabase
          .from("broker_connections")
          .update({
            consecutive_refresh_failures: 0,
            last_refresh_at: ranAt,
          })
          .eq("id", row.id);
        continue;
      }

      const update = await supabase
        .from("broker_connections")
        .update({
          access_token_enc: encryptToken(out.access_token),
          refresh_token_enc: out.refresh_token
            ? encryptToken(out.refresh_token)
            : row.refresh_token_enc,
          expires_at: out.expires_at,
          consecutive_refresh_failures: 0,
          last_refresh_at: ranAt,
          updated_at: ranAt,
        })
        .eq("id", row.id);

      if (update.error) {
        results.push({
          id: row.id,
          broker: row.broker,
          status: "failed",
          note: `DB update failed: ${update.error.message}`,
        });
        await logAttempt(supabase, row, "failed",
          `DB update failed: ${update.error.message}`, null, ranAt);
        await bumpFailure(supabase, row, ranAt);
      } else {
        const note = `Refreshed · new expiry ${out.expires_at}`;
        results.push({
          id: row.id,
          broker: row.broker,
          status: "refreshed",
          note,
        });
        await logAttempt(supabase, row, "refreshed", note, out.expires_at, ranAt);
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : "refresh raised";
      results.push({ id: row.id, broker: row.broker, status: "failed", note: msg });
      await logAttempt(supabase, row, "failed", msg, null, ranAt);
      await bumpFailure(supabase, row, ranAt);
    }
  }

  return NextResponse.json({
    ok: true,
    candidates: rows?.length ?? 0,
    horizon,
    results,
  });
}

// ---- helpers -----------------------------------------------------------

type AuditStatus =
  | "refreshed"
  | "failed"
  | "skipped"
  | "no_refresher"
  | "malformed";

type ConnRow = {
  id: string;
  user_id: string;
  broker: string;
  consecutive_refresh_failures: number | null;
};

// eslint-disable-next-line @typescript-eslint/no-explicit-any
async function logAttempt(
  supabase: any,
  row: ConnRow,
  status: AuditStatus,
  note: string,
  newExpiresAt: string | null,
  ranAt: string
) {
  try {
    await supabase.from("broker_token_refresh_log").insert({
      broker_connection_id: row.id,
      user_id: row.user_id,
      broker: row.broker,
      status,
      note,
      new_expires_at: newExpiresAt,
      ran_at: ranAt,
    });
  } catch {
    // Audit log is best-effort; never fail the cron job because we
    // couldn't write a log row.
  }
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
async function bumpFailure(supabase: any, row: ConnRow, ranAt: string) {
  const next = (row.consecutive_refresh_failures ?? 0) + 1;
  const patch: Record<string, unknown> = {
    consecutive_refresh_failures: next,
    last_refresh_at: ranAt,
  };
  if (next >= MAX_FAILURES) {
    patch.status = "expired";
  }
  await supabase.from("broker_connections").update(patch).eq("id", row.id);
}

// ---- Per-broker refresh adapters ---------------------------------------
// Each fn takes the decrypted refresh_token, calls the broker's refresh
// endpoint, returns { access_token, refresh_token?, expires_at } or null.

type RefreshResult = {
  access_token: string;
  refresh_token?: string;
  expires_at: string;
};
type Refresher = (refreshToken: string) => Promise<RefreshResult | null>;

/**
 * Alpaca OAuth refresh. Alpaca's `/oauth/token` endpoint accepts the
 * standard `grant_type=refresh_token` exchange. Today Alpaca paper
 * tokens are long-lived (no `expires_in` returned for some integrations);
 * when that's the case we return null and the caller treats it as a
 * skip, not a failure. Once Alpaca starts issuing short-lived tokens
 * this code path activates automatically.
 *
 * Docs: https://alpaca.markets/docs/oauth/
 */
const refreshAlpaca: Refresher = async (refreshToken) => {
  const clientId = process.env.ALPACA_OAUTH_CLIENT_ID;
  const clientSecret = process.env.ALPACA_OAUTH_CLIENT_SECRET;
  if (!clientId || !clientSecret) {
    throw new Error(
      "ALPACA_OAUTH_CLIENT_ID / ALPACA_OAUTH_CLIENT_SECRET not configured."
    );
  }

  const body = new URLSearchParams({
    grant_type: "refresh_token",
    refresh_token: refreshToken,
    client_id: clientId,
    client_secret: clientSecret,
  });

  const res = await fetch("https://api.alpaca.markets/oauth/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: body.toString(),
  });

  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(
      `Alpaca refresh failed [${res.status}]: ${text.slice(0, 200)}`
    );
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const json = (await res.json()) as any;
  const accessToken = String(json.access_token ?? "");
  if (!accessToken) {
    throw new Error("Alpaca refresh: response missing access_token");
  }
  const expiresIn = Number(json.expires_in ?? 0);
  if (!expiresIn || !Number.isFinite(expiresIn)) {
    // Long-lived token — nothing to update. Treat as skip.
    return null;
  }
  const expiresAt = new Date(Date.now() + expiresIn * 1000).toISOString();
  return {
    access_token: accessToken,
    refresh_token: json.refresh_token ? String(json.refresh_token) : undefined,
    expires_at: expiresAt,
  };
};

const REFRESHERS: Partial<Record<string, Refresher>> = {
  alpaca: refreshAlpaca,
  "alpaca-live": refreshAlpaca,
  // webull: async (refresh) => { ... },
  // robinhood: async (refresh) => { ... },
};
