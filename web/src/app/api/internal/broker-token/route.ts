import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import * as crypto from "crypto";
import {
  getActiveToken,
  isTokenKeyConfigured
} from "@/lib/broker-connections";
import { getProvider } from "@/lib/broker-providers";

export const dynamic = "force-dynamic";

/**
 * Internal endpoint — the agents service calls this to look up a
 * user's per-broker OAuth access token at execute time. NOT for
 * browsers. Protected by AGENTS_SHARED_SECRET (Authorization: Bearer).
 *
 * Returns: { access_token, refresh_token?, expires_at? } or
 *          { error } with 4xx.
 */
export async function POST(request: Request) {
  // 1. Shared-secret check. Both sides set AGENTS_SHARED_SECRET; any
  //    mismatch (or missing config) refuses the call. Constant-time
  //    compare so a length difference does not leak via timing.
  const expected = process.env.AGENTS_SHARED_SECRET;
  if (!expected) {
    return NextResponse.json(
      { error: "AGENTS_SHARED_SECRET is not configured on the web service." },
      { status: 500 }
    );
  }
  const authHeader = request.headers.get("authorization") ?? "";
  const presented = authHeader.startsWith("Bearer ")
    ? authHeader.slice("Bearer ".length).trim()
    : "";
  const exp = Buffer.from(expected);
  const got = Buffer.from(presented);
  const ok =
    exp.length === got.length && crypto.timingSafeEqual(exp, got);
  if (!ok) {
    return NextResponse.json({ error: "Unauthorized." }, { status: 401 });
  }

  if (!isTokenKeyConfigured()) {
    return NextResponse.json(
      { error: "TREZO_TOKENS_KEY not configured — cannot decrypt tokens." },
      { status: 500 }
    );
  }

  let body: { user_id?: string; broker?: string };
  try {
    body = (await request.json()) as { user_id?: string; broker?: string };
  } catch {
    return NextResponse.json(
      { error: "Bad request body — expected JSON." },
      { status: 400 }
    );
  }
  const user_id = (body.user_id ?? "").trim();
  const brokerKey = (body.broker ?? "").trim();
  if (!user_id || !brokerKey) {
    return NextResponse.json(
      { error: "user_id and broker are required." },
      { status: 400 }
    );
  }
  const provider = getProvider(brokerKey);
  if (!provider) {
    return NextResponse.json({ error: "Unknown broker." }, { status: 404 });
  }

  const token = await getActiveToken(user_id, provider.key);
  if (!token) {
    return NextResponse.json(
      { error: "No active connection for that user + broker." },
      { status: 404 }
    );
  }
  return NextResponse.json({
    access_token: token.access_token,
    refresh_token: token.refresh_token,
    expires_at: token.expires_at,
    broker: provider.key
  });
}
