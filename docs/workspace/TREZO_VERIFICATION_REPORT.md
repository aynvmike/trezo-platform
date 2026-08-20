# Trezo — Verification Report

A scan of the platform for accuracy and security, run 2026-05-22 after
Phase 9.5. Three parts: the agent/tool accuracy scan, the authentication
and security review, and a full sitemap.

**Scope:** this is a structural review — it checks that the safeguards
are present and wired correctly across the code and database. It is not
a live penetration test and does not replace one before real-money
trading goes live in Phase 10.

---

## 1. Agent & tool accuracy scan

**Result: accurate. No discrepancies.**

- **15 agents defined, 15 registered.** Every agent class in the code is
  registered in the runtime bootstrap, and the bootstrap reports
  `count=15`. Nothing is defined-but-forgotten or registered-twice.
- **All 65 agent code files parse cleanly** (syntax sweep).
- **Each agent has a clear, single role.** The full roster:

  1. Pattern Detection — candlestick patterns, scores trade confidence.
  2. STMS Scanner — small-cap momentum, 7-11 AM ET.
  3. ORB Scanner — opening-range breakouts, 9:35-11:30 AM ET.
  4. Crypto Scanner — 24/7 XRP/ETH/SOL, SCALP/SWING/DCA modes.
  5. Options Scanner — Dividend Wheel and options ideas (modeled).
  6. Risk Manager — the gatekeeper; approves or vetoes every signal.
  7. Trade Execution — routes approved signals to Alpaca / paper engine.
  8. Position Monitor — watches open positions, closes on stop/target.
  9. Tax Optimizer — running tax-position and tax-strategy nudges.
  10. KINDRIP — scheduled children's-account contributions (Layer 7).
  11. Market Sentiment — news scanning and event flags.
  12. Research — earnings and ex-dividend calendar watch.
  13. Adaptive Scope — adjusts strategy scope to regime and news.
  14. User Support — answers questions about decisions and outcomes.
  15. Strategy Discovery — win/loss metrics and review prompts.

- **Tools / endpoints.** The web app reaches the agent runtime through
  four API routes (list, activity feed, toggle, trigger). All four are
  accounted for and functioning. The two that change state (toggle,
  trigger) were hardened in this pass — see section 2.

---

## 2. Authentication & security review

**Result: solid foundation. One gap found and fixed; minor cleanup
items noted.**

### What is working correctly

- **Row-Level Security (RLS) is on for every table that holds user
  data.** All 23 database tables have RLS enabled with "see only your
  own rows" policies. The database defaults to deny — a user cannot
  read or change another user's records even if they tried.
- **The web app only ever uses the public "anon" key.** The powerful
  service-role key never appears in browser-facing code; it is confined
  to the server-side agent service. This is exactly right.
- **Every dashboard page checks for a signed-in user** and redirects to
  sign-in if there is none — all 19 pages verified.
- **Every server action checks the session** before reading or writing
  (all 4 verified). A logged-out request cannot save settings or data.
- **Session refresh middleware** runs on every page request, keeping
  logins valid without exposing protected pages.
- **The API server verifies the login token** (a signed Supabase JWT)
  before serving protected routes.

### Gap found and FIXED in this pass

- **Agent toggle and trigger endpoints were unauthenticated.** The two
  API routes that switch an agent on/off or fire a manual run accepted
  POST requests without checking for a signed-in user. Anyone able to
  reach the server could have toggled agents or triggered runs.
  **Fix applied:** both endpoints now require a valid session and
  return "401 Not signed in" otherwise — matching every other
  state-changing route in the app.

### Notes — acceptable now, revisit later

- **Read-only data endpoints are open.** The market-data routes (crypto
  prices, stock quotes, pattern lookups, ticker search) proxy public
  information and are fine to leave open. The agent list and activity
  feed are also open; that is acceptable while Trezo is single-user, but
  when it becomes multi-user (the per-user runtime planned for Phase 5b)
  those should be scoped to the signed-in user.
- **Orphaned legacy tables.** Three tables from the earliest migrations
  — `kindrip_contributions`, `trades`, and `agent_logs` — are no longer
  used by any code (the live system uses `kindrip_transactions`,
  `paper_positions`, and `agent_messages`). They still have RLS on, so
  they are locked, not exposed — this is housekeeping, not a hole.
  Recommendation: a small cleanup migration to drop them so the schema
  matches the running system.

### Before real money (Phase 10)

The current safeguards are appropriate for paper trading. Before live
brokerage, recommend: a live penetration test, rate-limiting on auth and
trading endpoints, and a secrets-rotation check on all API keys.

---

## 3. Sitemap

Every page and route in the platform.

### Public

- `/` — landing page.

### Account / authentication

- `/sign-in` — log in.
- `/sign-up` — create an account.
- `/forgot-password` — request a reset link.
- `/reset-password` — set a new password.
- `/auth/callback` — email-confirmation handler.
- `/auth/sign-out` — sign out.

### Onboarding

- `/onboarding` — four-step profile setup: identity, capital,
  discipline rules, and tax (including the optional tax-savings panel).

### Dashboard — overview & markets

- `/dashboard` — overview: activity feed, agent ticker, snapshot.
- `/dashboard/stocks` — stock watchlist view.
- `/dashboard/crypto` — crypto bot activity (XRP/ETH/SOL).
- `/dashboard/options` — options strategies (Layer 3).
- `/dashboard/wheel` — the Dividend Wheel (Layer 4/5).
- `/dashboard/yieldmax` — YieldMax income tracker.
- `/dashboard/patterns` — candlestick pattern detections.
- `/dashboard/stms` — small-cap momentum scanner.
- `/dashboard/strategy` — strategy library and Adaptive Scope log.

### Dashboard — trading, performance & planning

- `/dashboard/paper` — paper trading account, positions, vault.
- `/dashboard/performance` — win rate, profit factor, scorecard.
- `/dashboard/tax` — Tax Optimizer: estimate, quarterly payments, the
  Tax Strategy section, and KINDRIP child-account contributions.
- `/dashboard/kindrip` — KINDRIP children's portfolios (Layer 7).
- `/dashboard/watchlists` — manage watchlists.
- `/dashboard/watchlists/[id]` — a single watchlist's tickers.

### Dashboard — system & settings

- `/dashboard/agents` — agent board: status, toggle, trigger.
- `/dashboard/settings/profile` — capital, discipline, and tax fields.
- `/dashboard/settings/bot` — Bot Tuning: risk sliders, losing-streak
  limit, strategy toggles, capital allocation, autonomy mode.
- `/dashboard/settings/filters` — ethical-investing filters.

### API routes (used by the app, not visited directly)

- Agents: `/api/agents`, `/api/agents/feed`,
  `/api/agents/[name]/toggle`, `/api/agents/[name]/trigger`.
- Market data: `/api/crypto`, `/api/quotes`,
  `/api/patterns/[ticker]`, `/api/tickers/search`.
- Watchlists: `/api/watchlists` (+ `/[id]`, `/[id]/items`,
  `/[id]/items/[itemId]`).
- Other: `/api/filter-settings`, `/api/tax/export`.

---

## Summary

- Agent roster is accurate — 15 defined, 15 registered, all parse clean.
- Authentication is well-built; one unauthenticated mutation was found
  and fixed during this pass.
- Two follow-ups recommended: scope the agent list/feed per-user when
  Trezo goes multi-user, and drop three orphaned legacy tables.
- A live security test belongs in the Phase 10 (real-money) checklist.
