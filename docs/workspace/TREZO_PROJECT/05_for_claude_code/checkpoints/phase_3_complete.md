# Phase 3 — Watchlist + Ethical Filters — COMPLETE

> Built by Nova, 2026-05-19.

## What shipped

### Database (migrations 0004 + 0005)
- `ethical_exclusions` — global table of tickers excluded by category, tier, source, evidence. RLS allows read for any authenticated user; writes locked to service role.
- `ethical_filter_settings` — per-user opt-in categories (tobacco, weapons, fossil_fuels, private_prisons, gambling, predatory_lending, animal_testing, adult_entertainment, cannabis, crypto_mining). RLS self-only.
- `ethical_overrides` — audit log of every user override on a Tier 2/3/4 ticker. RLS self-only.
- `watchlist_items` extended with `ethical_override` boolean and `ethical_override_reason` text.
- Seed data: ~35 tickers across weapons / tobacco / fossil_fuels / private_prisons / gambling / cannabis / crypto_mining at Tier 4 (user-toggleable). Tier 1-3 default exclusions (SAM.gov / OFAC / SEC) will be populated by a daily sync job in Phase 5+ — for now Tier 4 demonstrates the full pipeline.

### Service layer
- `lib/services/ethical.ts` — `checkTicker(userId, ticker)` returns a `FilterDecision` (ok | blocked with tier/category/source/evidence/overridable). `getUserSettings` auto-creates defaults. `logOverride` writes to the audit log.
- `lib/watchlists.ts` — CRUD + seeding. `getOrSeedDefaultWatchlist` creates "Core Winners" (10 founder-winners tickers from TREZO_FOUNDER_WATCHLIST.md) on first call.

### API routes
- `GET /api/tickers/search?q=APPL` — Finnhub symbol autocomplete, 24h cache
- `GET/POST /api/watchlists` — list and create
- `GET/PATCH/DELETE /api/watchlists/[id]` — read/rename/delete
- `POST /api/watchlists/[id]/items` — add ticker, runs ethical filter, returns 201/403/409 depending on decision
- `PATCH/DELETE /api/watchlists/[id]/items/[itemId]` — update (notes, star, reorder up/down) and remove
- `GET/PATCH /api/filter-settings` — read/update user's ethical toggles

### UI
- `/dashboard/watchlists` — grid of all lists with item counts and Default badge, inline "New watchlist" form
- `/dashboard/watchlists/[id]` — detail with:
  - Live autocomplete (Finnhub) on the add-ticker input
  - One-click add from suggestions
  - CSV/text-list import (parses, validates ticker shape, sequentially attempts add)
  - Star, up/down reorder, remove
  - **Override dialog** with full evidence display, source attribution, free-text reason requirement (min 4 chars), and Tier-1 unoverridable enforcement
- `/dashboard/settings/filters` — toggle UI for the ten opt-in categories with per-category exclusion counts, Tier-1 always-on disclosure
- `/dashboard/stocks` — now reads the user's default watchlist (no more hardcoded preview) with friendly empty state and Finnhub-RTH note
- Sidebar: added "Watchlists" and "Filters" entries

## Exit criteria status

| Criterion | Status |
|---|---|
| User can add/remove tickers | ✅ via /dashboard/watchlists/[id] |
| Excluded tickers blocked with clear reasons | ✅ override dialog with evidence + source |
| User can toggle ethical filter categories | ✅ /dashboard/settings/filters with auto-save |
| Default watchlist loads on first sign-in | ✅ Core Winners seeded on first /dashboard/watchlists or /dashboard/stocks visit |

## Decisions made (worth remembering)

1. **Tier 4 only at this stage** — Tier 1/2/3 require daily sync jobs from SAM.gov/OFAC/SEC. Deferred to Phase 5 (agents). Today's filter is functional, demonstrable, and complete in shape — we'll backfill data as agents come online.
2. **Override flow logs everything** — `ethical_overrides` is per-user, queryable, and stays even after the watchlist item is deleted. Auditable trust.
3. **Tier-1 is hard-blocked at the API layer**, not just the UI — even a crafted POST with `override: true` is rejected with 403.
4. **Reorder uses up/down arrows, not drag-drop** — accessible by default, no extra dependency, mobile-friendly. Drag-drop polish can come in Phase 11.
5. **Seeding is idempotent** — `getOrSeedDefaultWatchlist` only inserts on first call; never duplicates.
6. **`/dashboard/stocks` now reads the real watchlist** — so the previous hardcoded preview list is gone. The default watchlist (Core Winners) gets seeded the first time the user lands on either /watchlists or /stocks.

## What the user needs to do before Phase 4

1. **Run migrations 0004 + 0005 in Supabase SQL editor**, in order:
   - `C:\Trezo\trezo-platform\db\migrations\0004_watchlists_and_ethical.sql`
   - `C:\Trezo\trezo-platform\db\migrations\0005_seed_ethical_exclusions.sql`
2. Hard-refresh the browser. Visit `/dashboard/watchlists` — your "Core Winners" list should appear.
3. Try adding XOM (fossil fuels — should block once you toggle Fossil Fuels on in `/dashboard/settings/filters`, then test the override dialog). Try LMT for weapons. Try AMD for a clean add.
4. CSV-import test: drop a comma-separated list like `AAPL,MSFT,GOOG,NVDA` into the import box.

## Known issues / open items

- The Strategy Discovery Agent's watchlist suggestions feature is Phase 10 — not in scope today.
- Finnhub free tier doesn't always return all CIK-mapped tickers in `/search`. Edge cases (very small caps) may not autocomplete; user can still type the symbol and add manually.
- Drag-drop reorder uses arrow buttons. Phase 11 polish can switch to native HTML5 drag.

## Next phase starting point

→ Phase 4: Pattern Detection Engine (port `isHammer()` + 6-factor scoring + 12 candlestick patterns + multi-timeframe confluence).
