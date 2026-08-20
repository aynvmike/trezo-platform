# Checkpoint — Generic broker OAuth framework + Alpaca Connect

Date: 2026-05-26
Direction: "no keys, no copy-paste — OAuth only, for every broker."

## What was built (framework, applies to every future broker)
- db/migrations/0026_broker_connections.sql — one table per-user per-
  broker, holds opaque encrypted ciphertext only. RLS to self.
- web/src/lib/broker-providers.ts — provider registry. Each provider
  declares authorize_url, token_url, scopes, env vars for client_id/
  client_secret, redirect_path, status ("available" or "planned").
  Adding a new broker = one row in this array; nothing else changes.
- web/src/lib/broker-connections.ts — server-only encryption (AES-256-
  GCM via Node crypto, key from TREZO_TOKENS_KEY, 32 bytes hex). Save,
  list, disconnect, and getActiveToken helpers.
- web/src/app/api/brokers/[broker]/authorize/route.ts — GET starts
  the OAuth dance: state cookie + 302 to provider's authorize URL.
- web/src/app/api/brokers/[broker]/callback/route.ts — GET receives
  the redirect, verifies state, exchanges code for tokens, encrypts +
  persists, redirects back to /settings/connections with status.
- web/src/app/api/brokers/[broker]/disconnect/route.ts — POST drops
  the row.
- web/src/app/dashboard/settings/connections/page.tsx — lists every
  provider as a card. Connect / Disconnect actions. Shows status,
  surfaces error reasons returned by the callback in plain words.
- web/src/components/dashboard/nav-config.ts — "Connections" added
  to the Settings sidebar group.

## Providers shipped in this turn
- Alpaca (Paper) — AVAILABLE. URLs and scopes wired:
    authorize: https://app.alpaca.markets/oauth/authorize
    token:     https://api.alpaca.markets/oauth/token
    scopes:    account:write trading data
  Requires env on the web service:
    ALPACA_OAUTH_CLIENT_ID, ALPACA_OAUTH_CLIENT_SECRET
    NEXT_PUBLIC_BASE_URL (so the redirect_uri is computable)
    TREZO_TOKENS_KEY (64 hex chars, 32 bytes)
  Plus on the Alpaca OAuth app config:
    redirect URL = ${NEXT_PUBLIC_BASE_URL}/api/brokers/alpaca/callback
- Alpaca (Live), IBKR, Robinhood, Plaid — PLANNED placeholder cards
  so the user sees the roadmap. Adding the real OAuth is a one-row
  change in broker-providers.ts plus the broker registration step.

## Security shape
- DB never sees plaintext tokens. Only the web service has
  TREZO_TOKENS_KEY.
- OAuth state cookie is HttpOnly + Secure + SameSite=Lax, 10-minute
  TTL — prevents CSRF on the callback.
- Disconnect is one POST; we drop the row, the broker still owns the
  user's account, and Trezo retains no plaintext.
- RLS guarantees a user can only ever see / mutate their own
  connection rows.

## Open follow-up
- Wire the agents service to pick the per-user token from
  broker_connections (via an internal endpoint exposed by web). Today
  the agents still use the env ALPACA_API_KEY for routing — once the
  read path on agents side reads per-user tokens, the env key becomes
  the optional fallback only.
- Token refresh job for providers that issue short-lived tokens with
  refresh tokens.
- A small UI on Profile / Connections to "re-authorise" when a token
  expires.
