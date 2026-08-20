# Checkpoint — Agents read per-user broker tokens

Date: 2026-05-26

## Safety housekeeping
.env.example was again carrying real keys (ALPACA, ANTHROPIC, FINNHUB,
UPSTASH). Moved the new Alpaca paper keys ($5k account) into
agents/.env, reset .env.example to safe placeholders for every known
sensitive key. Same fix pattern as the prior Upstash leak.

## What was built
- web/src/app/api/internal/broker-token/route.ts (new)
  - POST { user_id, broker }. Auth: Bearer AGENTS_SHARED_SECRET (constant-
    time compare, refuses on any mismatch). Returns the decrypted
    access_token + refresh_token + expires_at from broker_connections.
  - 401/404/500 with explicit reasons.

- agents/app/integrations/web_tokens.py (new)
  - get_user_broker_token(user_id, broker) -> BrokerToken | None.
    Calls /api/internal/broker-token over httpx. 2-minute per-(user,
    broker) cache so a trade flurry doesn't round-trip every call.
  - invalidate_user_token() for post-401 cache busting.

- agents/app/brokers/alpaca.py
  - New @dataclass UserToken and _headers_for(token) helper.
  - _get / _post / _delete + get_account / get_clock /
    submit_bracket_order all accept an optional `token` arg. When
    given, use the bearer; otherwise fall back to env keys.

- agents/app/agents/trade_execution.py
  - _execute_alpaca now looks up the per-user token first via
    get_user_broker_token. Passes it through to get_clock,
    get_account, submit_bracket_order.
  - Adds `routed_via` to every execute / info payload: "user-oauth"
    when the user's connected account was used, "env-keys" for the
    legacy fallback. Lets us audit which route each trade took.

## Operational notes
Add on the web service:
  AGENTS_SHARED_SECRET=$(openssl rand -hex 32)
  TREZO_TOKENS_KEY=$(openssl rand -hex 32)         (already)
  NEXT_PUBLIC_BASE_URL=https://your-trezo-url      (already)
  ALPACA_OAUTH_CLIENT_ID + ALPACA_OAUTH_CLIENT_SECRET

Add on the agents service (same value):
  AGENTS_SHARED_SECRET=<same string as on web>
  WEB_INTERNAL_BASE_URL=http://localhost:3000      (or production URL)

## How a per-user trade flows now
1. User taps Connect on the Alpaca Paper card → OAuth → token stored
   encrypted in broker_connections.
2. Pattern Detection fires a signal with user_id.
3. Risk Manager approves it.
4. Trade Execution looks up that user's token via
   /api/internal/broker-token, gets the access_token plaintext back,
   passes it to submit_bracket_order. The trade lands in THAT user's
   Alpaca paper account, not Trezo's.
5. The execute message tags routed_via=user-oauth so the audit trail
   shows it took the per-user path.

## Verified
- All touched files compile / balance.
- Functional import test confirmed UserToken + _headers_for + the
  agents-side web_tokens helper resolve cleanly.

## What unblocked
- Beta tester rollout — each of Mike's 3 testers can now Connect
  their own Alpaca account on Settings → Connections, and their
  trades route through their own broker, not through the shared env
  key.
