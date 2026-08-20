# Checkpoint — Dividends page cleaned, picker moved to Watchlists

Date: 2026-05-26

## What changed
- web/src/app/dashboard/yieldmax/page.tsx (rewritten) — strips the big
  ETF library + custom-add form. Now shows only the user's actual
  dividend holdings (the YieldMaxTracker). Empty state explicitly
  points to Watchlists with an "Add holdings →" button in the header
  and a plain-language prompt in the empty card.

- web/src/app/dashboard/watchlists/page.tsx — now passes the rich
  INCOME_ETF_LIBRARY (54 ETFs across 8 families) and the addHolding
  action through to the grid.

- web/src/app/dashboard/watchlists/_watchlist-grid.tsx (rewritten) —
  the YieldMax card became the "Income ETF picker" card. Opening it
  reveals a grouped library (by family) with real Add buttons and a
  custom-ticker add form. Adding from here writes to the Dividends
  layer (asset_type=yieldmax in user_positions) and revalidates both
  pages.

- web/src/app/dashboard/yieldmax/_actions.ts — addHolding now accepts
  an optional `name` form field (library passes it). For custom adds,
  best-effort Finnhub enrichment fills the company name from market
  data when FINNHUB_API_KEY is set on the web service. Stored in the
  user_positions.notes column. Revalidates /dashboard/yieldmax AND
  /dashboard/watchlists so both pages refresh after an add.

- web/src/components/widgets/yieldmax-tracker.tsx — Position type
  gains optional `name`; the tracker renders the company name under
  the ticker on each holding card.

## UX outcome
1. Dividends page is now a clean holdings view, exactly what Mike asked.
2. The picker, custom-add and family browsing live in Watchlists —
   the central "what do I track" page.
3. Custom adds aren't limited to the prompt's curated list; any
   ticker the market data feed knows can be added, and the company
   name auto-fills from Finnhub.
4. The held-state and add-button states stay in sync between the
   two pages via dual revalidation.

## Verified
All 5 touched files balanced 0/0/0.
