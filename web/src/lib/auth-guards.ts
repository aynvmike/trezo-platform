/**
 * Route-handler auth guards.
 *
 * ADM-01 / ADM-02 / ADM-04 / SWEEP-01: the platform had no owner concept —
 * any signed-in user could hit /api/admin/* and the global-op routes
 * (toggle/trigger agents, reconcile, place-leg, ...). These helpers give
 * every route handler one line to require a session (requireUser) or the
 * owner allowlist (requireOwner).
 *
 * Owner = the session user's id appears in TREZO_OWNER_USER_IDS
 * (comma-separated Supabase auth user ids, server env). If that env var is
 * unset or empty, requireOwner FAILS CLOSED (403) and logs once — unset is
 * never "everyone is owner".
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

let warnedUnsetOnce = false;

/** True only when the id is explicitly allowlisted. Unset list => false. */
export function isOwnerUserId(userId: string | null | undefined): boolean {
  if (!userId) return false;
  const ids = ownerUserIds();
  if (ids.length === 0) {
    if (!warnedUnsetOnce) {
      warnedUnsetOnce = true;
      console.error(
        `[auth-guards] ${OWNER_IDS_ENV} is not set — every owner-only route (admin/*, agent toggle/trigger, reconcile, place-leg, ...) will return 403 until it is. Set it to the owner's Supabase auth user id.`
      );
    }
    return false;
  }
  return ids.includes(userId);
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

/** 401 without a session; 403 unless the session user is an allowlisted owner. */
export async function requireOwner(supabase: SupabaseClient): Promise<GuardResult> {
  const r = await requireUser(supabase);
  if (!r.ok) return r;
  if (!isOwnerUserId(r.user.id)) {
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
