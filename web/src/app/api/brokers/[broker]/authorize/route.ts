import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import * as crypto from "crypto";
import { createClient } from "@/lib/supabase/server";
import { getProvider } from "@/lib/broker-providers";
import { isTokenKeyConfigured } from "@/lib/broker-connections";

export const dynamic = "force-dynamic";

/**
 * GET /api/brokers/{broker}/authorize
 *
 * Kicks off the OAuth dance. Generates a CSRF state, stashes it in a
 * short-lived HttpOnly cookie, and 302s the user to the provider's
 * authorize URL. The provider posts back to /callback with the code.
 */
export async function GET(
  request: Request,
  { params }: { params: { broker: string } }
) {
  const supabase = createClient();
  const {
    data: { user }
  } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ error: "Not signed in." }, { status: 401 });
  }

  const provider = getProvider(params.broker);
  if (!provider || provider.status !== "available") {
    return NextResponse.json(
      { error: "Broker not available for connect yet." },
      { status: 404 }
    );
  }
  if (!isTokenKeyConfigured()) {
    return NextResponse.json(
      {
        error:
          "TREZO_TOKENS_KEY is not set on the web service — encrypted storage of broker tokens is offline."
      },
      { status: 500 }
    );
  }
  const clientId = provider.client_id_env
    ? process.env[provider.client_id_env]
    : undefined;
  if (!clientId || !provider.authorize_url) {
    return NextResponse.json(
      {
        error: `${provider.label} OAuth client is not registered. Set ${provider.client_id_env} (and the secret) on the web service.`
      },
      { status: 500 }
    );
  }

  const state = crypto.randomBytes(24).toString("hex");
  // OAUTH-4: `secure: true` unconditionally meant the browser dropped the
  // state cookie when the dashboard is served over plain HTTP (Tailscale),
  // so every callback failed with state_mismatch. Set `secure` from the
  // actual request protocol (proxy header first, then the URL).
  const forwardedProto = (request.headers.get("x-forwarded-proto") ?? "")
    .split(",")[0]
    .trim()
    .toLowerCase();
  const isHttps =
    forwardedProto === "https" ||
    (!forwardedProto && new URL(request.url).protocol === "https:");
  cookies().set(`trezo_oauth_state_${provider.key}`, state, {
    httpOnly: true,
    secure: isHttps,
    sameSite: "lax",
    path: "/",
    maxAge: 600
  });

  const base = (process.env.NEXT_PUBLIC_BASE_URL ?? "").replace(/\/+$/, "");
  const redirect_uri = `${base}${provider.redirect_path}`;
  const url = new URL(provider.authorize_url);
  url.searchParams.set("response_type", "code");
  url.searchParams.set("client_id", clientId);
  url.searchParams.set("redirect_uri", redirect_uri);
  if (provider.scopes) url.searchParams.set("scope", provider.scopes);
  url.searchParams.set("state", state);

  return NextResponse.redirect(url.toString(), { status: 302 });
}
