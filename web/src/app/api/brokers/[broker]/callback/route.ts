import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { createClient } from "@/lib/supabase/server";
import { getProvider } from "@/lib/broker-providers";
import { saveConnection } from "@/lib/broker-connections";

export const dynamic = "force-dynamic";

/**
 * GET /api/brokers/{broker}/callback
 *
 * The provider redirected the user back with ?code=... &state=...
 * We exchange the code for tokens, encrypt + persist, then send the
 * user back to /dashboard/settings/connections with a status flag.
 */
export async function GET(
  request: Request,
  { params }: { params: { broker: string } }
) {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  const redirectBase = "/dashboard/settings/connections";
  if (!user) return NextResponse.redirect(new URL("/sign-in", request.url));

  const provider = getProvider(params.broker);
  if (!provider || provider.status !== "available" || !provider.token_url) {
    return NextResponse.redirect(
      new URL(`${redirectBase}?error=unsupported`, request.url)
    );
  }

  const { searchParams } = new URL(request.url);
  const code = searchParams.get("code");
  const state = searchParams.get("state");
  const errorParam = searchParams.get("error");
  if (errorParam) {
    return NextResponse.redirect(
      new URL(
        `${redirectBase}?error=${encodeURIComponent(errorParam)}`,
        request.url
      )
    );
  }
  if (!code || !state) {
    return NextResponse.redirect(
      new URL(`${redirectBase}?error=missing_code`, request.url)
    );
  }

  const cookieStore = cookies();
  const expectedState = cookieStore.get(`trezo_oauth_state_${provider.key}`)?.value;
  if (!expectedState || expectedState !== state) {
    return NextResponse.redirect(
      new URL(`${redirectBase}?error=state_mismatch`, request.url)
    );
  }
  cookieStore.delete(`trezo_oauth_state_${provider.key}`);

  const clientId = provider.client_id_env
    ? process.env[provider.client_id_env]
    : undefined;
  const clientSecret = provider.client_secret_env
    ? process.env[provider.client_secret_env]
    : undefined;
  if (!clientId || !clientSecret) {
    return NextResponse.redirect(
      new URL(`${redirectBase}?error=oauth_unconfigured`, request.url)
    );
  }

  const base = (process.env.NEXT_PUBLIC_BASE_URL ?? "").replace(/\/+$/, "");
  const redirect_uri = `${base}${provider.redirect_path}`;

  // Standard OAuth2 token exchange — form-encoded.
  const body = new URLSearchParams({
    grant_type: "authorization_code",
    code,
    client_id: clientId,
    client_secret: clientSecret,
    redirect_uri
  });

  let tokenResp: {
    access_token?: string;
    refresh_token?: string;
    token_type?: string;
    expires_in?: number;
    scope?: string;
  };
  try {
    const r = await fetch(provider.token_url, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body
    });
    if (!r.ok) {
      const detail = await r.text().catch(() => "");
      return NextResponse.redirect(
        new URL(
          `${redirectBase}?error=token_exchange&detail=${encodeURIComponent(detail.slice(0, 200))}`,
          request.url
        )
      );
    }
    tokenResp = await r.json();
  } catch (e) {
    return NextResponse.redirect(
      new URL(`${redirectBase}?error=token_exchange_failed`, request.url)
    );
  }

  if (!tokenResp.access_token) {
    return NextResponse.redirect(
      new URL(`${redirectBase}?error=no_token`, request.url)
    );
  }

  const expires_at = tokenResp.expires_in
    ? new Date(Date.now() + Number(tokenResp.expires_in) * 1000).toISOString()
    : null;

  const saved = await saveConnection({
    user_id: user.id,
    broker: provider.key,
    access_token: tokenResp.access_token,
    refresh_token: tokenResp.refresh_token ?? null,
    expires_at,
    scopes: tokenResp.scope ?? provider.scopes ?? null
  });
  if (!saved.ok) {
    return NextResponse.redirect(
      new URL(
        `${redirectBase}?error=save_failed&detail=${encodeURIComponent(saved.error ?? "")}`,
        request.url
      )
    );
  }

  return NextResponse.redirect(
    new URL(`${redirectBase}?connected=${provider.key}`, request.url)
  );
}
