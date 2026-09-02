/**
 * Route-handler auth guards.
 *
 * ADM-01 / ADM-02 / ADM-04 / SWEEP-01: the platform had no owner concept —
 * any signed-in user could hit /api/admin/* and the global-op routes
 * (toggle/trigger agents, reconcile, place-leg, ...). These helpers give
 * every route handler one line to require a session (requireUser) or the
 * owner check (requireOwner).
 *
 * WHO IS AN OWNER (2026-09-02):
 *   1. If TREZO_OWNER_USER_IDS (comma-separated Supabase auth user ids) is
 *      set in the server env, it is the allowlist and nothing else counts.
 *   2. Otherwise ownership is DERIVED FROM THE DATABASE: the session user
 *      owns at least one active row in trading_accounts (owner_id = their
 *      auth uid, is_active = true). That table is where migration 0045
 *      registered the person→accounts→books model, and RLS lets a person
 *      read only their own rows, so the lookup runs on the caller's own
 *      session client. A signed-up user with no books gets 403.
 *   The DB rule exists so the operator does not have to edit server env by
 *   hand to keep their own admin buttons working; the env allowlist remains
 *   the stricter override for a multi-owner deployment. Neither branch ever
 *   treats "unset" as "everyone is owner": no env AND no books → 403.
 *
 * Usage:
 *   const supabase = createClient();
 *   const guard = await requireOwner(supabase);
 *   if (!guard.ok) return guard.response;
 *   const user = guard.user;
 */

import { NextResponse } from "next/server";
import type { SupabaseClient, User } from "@supabase/supabase-js";

export const OWNER_IDS_ENV = "TREZO_OWNER_USER_IDS";

export type GuardResult =
  | { ok: true; user: User }
  | { ok: false; user: null; response: NextResponse };

/** Parse the owner allowlist from env. Empty array when unset/blank. */
export function ownerUserIds(): string[] {
  return (process.env[OWNER_IDS_ENV] ?? "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

let loggedModeOnce = false;

/** True only when the id is explicitly allowlisted. Unset list => false. */
export function isOwnerUserId(userId: string | null | undefined): boolean {
  if (!userId) return false;
  const ids = ownerUserIds();
  if (ids.length === 0) return false;
  return ids.includes(userId);
}

/**
 * DB-derived ownership: does this session user own >= 1 active trading
 * account? Runs on the caller's RLS-scoped client, so it can only ever see
 * the caller's own rows. A failed read is NOT ownership (fail closed).
 */
export async function ownsAnActiveBook(
  supabase: SupabaseClient,
  userId: string
): Promise<boolean> {
  try {
    const { data, error } = await supabase
      .from("trading_accounts")
      .select("account_key")
      .eq("owner_id", userId)
      .eq("is_active", true)
      .limit(1);
    if (error) {
      console.error(
        `[auth-guards] trading_accounts read failed while resolving ownership: ${error.message}`
      );
      return false;
    }
    return Array.isArray(data) && data.length > 0;
  } catch (e) {
    console.error(
      `[auth-guards] trading_accounts read threw while resolving ownership: ${String(e)}`
    );
    return false;
  }
}

/** 401 unless there is a valid Supabase session on the request. */
export async function requireUser(supabase: SupabaseClient): Promise<GuardResult> {
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) {
    return {
      ok: false,
      user: null,
      response: NextResponse.json(
        { ok: false, error: "Not signed in." },
        { status: 401 }
      )
    };
  }
  return { ok: true, user };
}

/**
 * 401 without a session; 403 unless the session user is an owner — by the
 * env allowlist when set, otherwise by owning an active trading account.
 */
export async function requireOwner(supabase: SupabaseClient): Promise<GuardResult> {
  const r = await requireUser(supabase);
  if (!r.ok) return r;

  const allowlist = ownerUserIds();
  let owner: boolean;
  if (allowlist.length > 0) {
    owner = allowlist.includes(r.user.id);
    if (!loggedModeOnce) {
      loggedModeOnce = true;
      console.log(`[auth-guards] owner mode: ${OWNER_IDS_ENV} allowlist (${allowlist.length} id(s))`);
    }
  } else {
    owner = await ownsAnActiveBook(supabase, r.user.id);
    if (!loggedModeOnce) {
      loggedModeOnce = true;
      console.log(
        `[auth-guards] owner mode: derived from trading_accounts (set ${OWNER_IDS_ENV} to override with an explicit allowlist)`
      );
    }
  }

  if (!owner) {
    return {
      ok: false,
      user: null,
      response: NextResponse.json(
        { ok: false, error: "Owner only." },
        { status: 403 }
      )
    };
  }
  return r;
}
