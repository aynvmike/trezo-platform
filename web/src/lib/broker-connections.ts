/**
 * Server-only helpers for storing and reading per-user broker tokens.
 * The DB stores opaque ciphertext; only the web service can read or
 * write because only it holds TREZO_TOKENS_KEY (32-byte key, hex).
 *
 * The bigger point — Mike's note: Trezo never asks the user to paste
 * keys, never holds plaintext at rest, never copies broker secrets
 * into screens. The OAuth round-trip is the only path; this module is
 * the only place tokens ever exist in cleartext at runtime.
 */

import * as crypto from "crypto";
import type { SupabaseClient } from "@supabase/supabase-js";
import { createClient } from "@/lib/supabase/server";
import type { BrokerKey } from "@/lib/broker-providers";

const KEY_ENV = "TREZO_TOKENS_KEY";

// OAUTH-8: a token whose expiry is within this window of "now" is treated as
// already expired, so a caller never receives a token that dies in flight.
const EXPIRY_SKEW_MS = 60 * 1000;

export type ConnectionRow = {
  id: string;
  broker: BrokerKey;
  account_id: string | null;
  expires_at: string | null;
  scopes: string | null;
  status: "active" | "expired" | "revoked";
  connected_at: string;
};

function loadKey(): Buffer {
  const raw = process.env[KEY_ENV];
  if (!raw) {
    throw new Error(
      `${KEY_ENV} is not set on the web service — broker connections cannot be encrypted.`
    );
  }
  const buf = Buffer.from(raw, "hex");
  if (buf.length !== 32) {
    throw new Error(`${KEY_ENV} must be a 64-character hex string (32 bytes).`);
  }
  return buf;
}

/** Encrypt a string with AES-256-GCM. Returns "nonceB64:cipherB64". */
export function encryptToken(plaintext: string): string {
  const key = loadKey();
  const nonce = crypto.randomBytes(12);
  const cipher = crypto.createCipheriv("aes-256-gcm", key, nonce);
  const enc = Buffer.concat([cipher.update(plaintext, "utf8"), cipher.final()]);
  const tag = cipher.getAuthTag();
  return `${nonce.toString("base64")}:${Buffer.concat([enc, tag]).toString("base64")}`;
}

/** Decrypt a stored "nonceB64:cipherB64" back to plaintext. */
export function decryptToken(encoded: string): string {
  const key = loadKey();
  const [nonceB64, blobB64] = encoded.split(":");
  if (!nonceB64 || !blobB64) throw new Error("Malformed encrypted token.");
  const nonce = Buffer.from(nonceB64, "base64");
  const blob = Buffer.from(blobB64, "base64");
  // The last 16 bytes are the auth tag.
  const tag = blob.subarray(blob.length - 16);
  const ct = blob.subarray(0, blob.length - 16);
  const decipher = crypto.createDecipheriv("aes-256-gcm", key, nonce);
  decipher.setAuthTag(tag);
  return Buffer.concat([decipher.update(ct), decipher.final()]).toString(
    "utf8"
  );
}

export type SaveConnectionInput = {
  user_id: string;
  broker: BrokerKey;
  account_id?: string | null;
  access_token: string;
  refresh_token?: string | null;
  expires_at?: string | null;
  scopes?: string | null;
};

export async function saveConnection(
  input: SaveConnectionInput
): Promise<{ ok: boolean; error?: string }> {
  const supabase = createClient();
  try {
    const access_token_enc = encryptToken(input.access_token);
    const refresh_token_enc = input.refresh_token
      ? encryptToken(input.refresh_token)
      : null;
    const { error } = await supabase.from("broker_connections").upsert(
      {
        user_id: input.user_id,
        broker: input.broker,
        account_id: input.account_id ?? null,
        access_token_enc,
        refresh_token_enc,
        expires_at: input.expires_at ?? null,
        scopes: input.scopes ?? null,
        status: "active",
        updated_at: new Date().toISOString()
      },
      { onConflict: "user_id,broker" }
    );
    if (error) return { ok: false, error: error.message };
    return { ok: true };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : "unknown" };
  }
}

export async function listConnections(
  user_id: string
): Promise<ConnectionRow[]> {
  const supabase = createClient();
  const { data } = await supabase
    .from("broker_connections")
    .select("id, broker, account_id, expires_at, scopes, status, connected_at")
    .eq("user_id", user_id)
    .order("connected_at", { ascending: false });
  return (data ?? []) as ConnectionRow[];
}

export async function disconnect(
  user_id: string,
  broker: BrokerKey
): Promise<{ ok: boolean; error?: string }> {
  const supabase = createClient();
  const { error } = await supabase
    .from("broker_connections")
    .delete()
    .eq("user_id", user_id)
    .eq("broker", broker);
  if (error) return { ok: false, error: error.message };
  return { ok: true };
}

/**
 * Look up the active per-user token for a broker, returning plaintext
 * for upstream use (the agents service calls this via an internal API).
 * Returns null if the row is missing, expired (status or expires_at within
 * EXPIRY_SKEW_MS of now — OAUTH-8), or revoked.
 *
 * `client` — AUTH-01/OAUTH-1: machine-to-machine callers have no user
 * session, so the default cookie client runs as anon and RLS hides every
 * row. Those callers must pass the service-role client from
 * "@/lib/supabase/admin". Session-backed callers can omit it.
 */
export async function getActiveToken(
  user_id: string,
  broker: BrokerKey,
  client?: SupabaseClient
): Promise<{
  access_token: string;
  refresh_token: string | null;
  expires_at: string | null;
} | null> {
  const supabase = client ?? createClient();
  const { data, error } = await supabase
    .from("broker_connections")
    .select(
      "access_token_enc, refresh_token_enc, expires_at, status"
    )
    .eq("user_id", user_id)
    .eq("broker", broker)
    .maybeSingle();
  // REV-SEC-01 (review 2026-09-01): a FAILED read must not read as "no
  // connection". Dropping `error` here turned every DB/RLS/network failure
  // into a 404 upstream, which is exactly how AUTH-01 hid for so long.
  // Throw so the caller can answer 5xx instead of "not connected".
  if (error) {
    throw new Error(`broker_connections read failed: ${error.message}`);
  }
  if (!data || data.status !== "active") return null;
  // OAUTH-8: expires_at <= now (+ skew) is not active, whatever `status` says.
  if (data.expires_at) {
    const expMs = Date.parse(data.expires_at as string);
    if (Number.isFinite(expMs) && expMs <= Date.now() + EXPIRY_SKEW_MS) {
      return null;
    }
  }
  try {
    const access_token = decryptToken(data.access_token_enc as string);
    const refresh_token = (data.refresh_token_enc as string | null)
      ? decryptToken(data.refresh_token_enc as string)
      : null;
    return {
      access_token,
      refresh_token,
      expires_at: (data.expires_at as string | null) ?? null
    };
  } catch {
    return null;
  }
}

export function isTokenKeyConfigured(): boolean {
  const raw = process.env[KEY_ENV];
  if (!raw) return false;
  try {
    return Buffer.from(raw, "hex").length === 32;
  } catch {
    return false;
  }
}
