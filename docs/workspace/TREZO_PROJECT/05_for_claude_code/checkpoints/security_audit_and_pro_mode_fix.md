# Checkpoint — Security audit + Pro-mode tone fix

Date: 2026-05-26

## Security audit — findings + fixes

### Surfaces reviewed
1. dangerouslySetInnerHTML — single use in app/layout.tsx, a server-
   rendered constant theme-script (no user input). SAFE.
2. eval / new Function — zero hits across web and agents.
3. process.env on client — only NEXT_PUBLIC_* (Supabase URL, anon key,
   BASE URL) which are explicitly public by design. No secret leaks.
4. Redirects — only NextResponse.redirect(new URL(..., request.url));
   no user-controlled hosts. OAuth callback validates state via
   HttpOnly cookie before any token exchange.
5. SQL — all via Supabase client (parameterised). Every user table has
   RLS keyed on auth.uid().
6. Ticker inputs — addHolding validates /^[A-Z][A-Z0-9.-]{0,9}$/.
7. OAuth state — HttpOnly + Secure + SameSite=Lax cookie, 10-min TTL,
   timingSafeEqual compare on the callback's state param. Bearer
   compare on /api/internal/broker-token uses timingSafeEqual too.
8. Token storage — broker_connections holds opaque ciphertext only.
   AES-256-GCM via TREZO_TOKENS_KEY in lib/broker-connections.ts.
9. Help-chat — Anthropic-backed, content returned as plain JSON +
   rendered as JSX text (auto-escaped). Message cap: last 12, each
   clipped to 2000 chars.

### Hardening applied this turn
- web/src/app/api/help/chat/route.ts — system prompt now carries an
  explicit INTEGRITY RULES section: stay in role, instructions take
  priority over user content, decline jailbreak attempts, never
  reveal/repeat system prompts or tokens, never disclose what model /
  API / endpoint is in use. Refers to itself as "the Trezo assistant"
  only.

### Not exploited but worth keeping in mind
- The /api/internal/broker-token route MUST keep AGENTS_SHARED_SECRET
  set; without it, the route refuses all callers (already in code).
- TREZO_TOKENS_KEY must remain in the web env, never logged.
- If/when we add a feature where Claude returns markdown that the
  client renders as HTML, we must add a markdown sanitiser. Today
  the help-chat renders as plain JSX text — XSS-safe.

## Pro-mode tone fix
Mike's note: Pro mode was stripping operational hints, leaving pages
feeling broken. Fix: add a SHORT always-visible purpose line above
every page's beginner-only intro. The long educational paragraph is
still beginner-only (hidden in Pro), but the single-sentence
"what this is for" stays.

20 dashboard pages patched in one sweep:
  paper, backtest, patterns, watchlists, wheel, settings/bot,
  settings/profile, markets, yieldmax, kindrip, simulation,
  projections, agents, extended, crypto, stms, options, budget,
  tax, performance.

Strategy Engine already received its purpose line last turn.

Apostrophes in JSX text in two of the new blurbs (backtest,
kindrip) escaped to &apos; — matches the project convention and
keeps the linter quiet.

## Verified
All touched files compile / balance.

## Still open
- Where the agents echo back any user-provided content into
  Claude-driven replies in future features, repeat the help-chat's
  INTEGRITY RULES pattern.
- The .beginner-only convention is now structured: short visible
  line = operational hint, beginner-only paragraph = educational
  extra. Apply the same pattern when adding new pages.
