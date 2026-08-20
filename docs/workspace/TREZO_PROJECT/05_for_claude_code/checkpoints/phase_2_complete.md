# Phase 2 — Dashboard + Data Integration — COMPLETE

> Built by Nova, 2026-05-19. Verified live by Mike on his Windows machine.

## What shipped

### Dashboard shell
- `app/dashboard/layout.tsx` — server-rendered layout with auth + onboarding gate, sticky header, sidebar, sign-out form
- `components/dashboard/nav-config.ts` — single source of truth for the seven-layer nav
- `components/dashboard/sidebar.tsx` — clickable for live layers (Crypto, Stock, YieldMax), greyed-out "Phase N" badges for future layers (Options, Wheel, Tax, Extended)
- `components/dashboard/mobile-nav.tsx` — hamburger drawer for `<md` viewports with body-scroll lock

### Data services
- `lib/cache.ts` — generic `cacheGetOrSet` helper. Uses Upstash Redis REST API if `UPSTASH_REDIS_REST_URL` + token are set; falls back to in-memory Map otherwise. Both branches handle errors gracefully.
- `lib/services/coingecko.ts` — XRP/ETH/SOL/BTC live prices, no API key, 30s TTL
- `lib/services/finnhub.ts` — single + batched quotes (30s), company profiles (24h), news (5m), with rate-limit catch

### API routes (Next.js)
- `GET /api/crypto?symbols=XRP,ETH,SOL` — returns CoinGecko prices via cache
- `GET /api/quotes?symbols=AMD,INTC,...` — returns Finnhub quotes via cache

### Widgets (all `"use client"`)
- `components/widgets/crypto-card.tsx` — three or four cards, polls every 30s, up/down arrows, gracefully handles fetch errors
- `components/widgets/stock-quotes.tsx` — table with horizontal scroll on narrow screens, 60s refresh
- `components/widgets/yieldmax-tracker.tsx` — total-value banner + per-ticker cards (shares, current value, day change), 60s refresh

### Pages
- `/dashboard` — overview: KPIs (capital, daily target), live crypto preview, watchlist preview, deep-links to layer pages
- `/dashboard/crypto` — Layer 1 with XRP/ETH/SOL/BTC and a "Phase 6 trading bot coming" footnote
- `/dashboard/stocks` — Layer 2 preview, AMD/INTC/CZR/WMT/AMSC/NVDA/TSLA/AAPL
- `/dashboard/yieldmax` — Layer 5 tracker. Seeds five default positions (AIYY/AMZY/GOOY/NVDY/TSLY at 30–50 shares each) on first visit.

### Database
- Migration `db/migrations/0003_user_positions.sql` — new `user_positions` table with RLS (user-owned), unique `(user_id, ticker, asset_type)`. Applied successfully in Supabase by Mike.
- Helper `lib/positions.ts` — `getYieldMaxPositions(userId)` reads existing rows or seeds defaults atomically.

### Tooling (Windows ergonomics)
- `start-web.bat`, `start-api.bat`, `start-agents.bat` — each auto-frees its port before launching (via `_freeport.bat` helper). Avoids the EADDRINUSE / port-3001 fallback trap.
- `start-all.bat` — opens all three in separate windows
- `kill-ports.bat` — manual cleanup for ports 3000 / 8000 / 8001
- `nuke-and-restart.bat`, `clean-restart.bat` — escalating recovery scripts for stuck dev caches

## Exit criteria status

| Criterion | Status |
|---|---|
| Live crypto prices on dashboard | ✅ via CoinGecko, 30s cache |
| Live stock quotes update every ~60s | ✅ via Finnhub, 30s server cache + 60s client poll |
| YieldMax positions display correctly | ✅ seeded defaults, live prices |
| Mobile view works | ✅ hamburger drawer, responsive grids, horizontal-scroll table |

## Decisions made (worth remembering)

1. **In-memory cache fallback** — code doesn't *require* Upstash. Same cache contract; works in any dev environment.
2. **Service layer in /web** rather than /api — Phase 2 data is read-only and consumed by the Next.js client. No need for the Express gateway to be in the path; the Next.js Route Handlers are simpler. Express comes back into play in later phases for trade execution and agents wiring.
3. **YieldMax positions seeded on first visit** — non-destructive, idempotent. User can edit later in a Phase 7 settings UI.
4. **Free-tier-friendly data approach** — Finnhub's `/quote` returns 0 outside regular trading hours on free tier. Documented in `phase_2_complete.md`; no workaround needed for Phase 2 since this is a price display, not a trading engine.
5. **30-day NAV health indicator from spec deferred** — requires Finnhub paid tier or alternative historical data. Showing today's % change as a proxy. Will revisit in Phase 4 when we add pattern detection (needs candles anyway).

## Known issues / open items

- Finnhub free tier returns 0 outside RTH (regular trading hours). Stock quote pages will show `$0.00` when markets are closed. This is upstream behavior, not a bug.
- Cumulative distributions on YieldMax positions are placeholder zeros. Real tracking requires a distribution feed — slated for Phase 7 (Tax Optimizer).
- Mike's Upstash account is wired in. Tokens are stored in the gitignored `.env.local` / `.env` files.

## What the user needs to do before Phase 3

Nothing required. Optional:
- If you want a settings UI to edit YieldMax share counts, that's a small lift we can drop into Phase 3 alongside the watchlist work.

## Next phase starting point

→ Phase 3: Watchlist Management + Ethical Filters.
- Custom watchlists with autocomplete, drag-to-reorder, CSV import
- Ethical exclusion list (default: weapons manufacturers per SAM.gov, expandable categories)
- Block flow with override + logging
- User settings UI for opt-in categories
