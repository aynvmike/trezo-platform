# Checkpoint — Paper sync fix · seeded watchlists · live wheel pricing

Date: 2026-05-26

## A. Paper-cash divergence fixed
The Paper page fetched Alpaca twice (once at the page level for the
KPI override, once inside AlpacaSnapshot). With cache: "no-store" the
two calls didn't dedupe — if either failed, the KPIs and the panel
disagreed (Mike saw $10k Trezo vs $5k Alpaca side by side).
Fix:
- web/src/components/dashboard/alpaca-snapshot.tsx — AlpacaSnapshot
  now accepts an optional `snap` prop and uses it when given.
- web/src/app/dashboard/paper/page.tsx — passes `snap={alpaca}` from
  the single page-level fetch through to AlpacaSnapshot. One source,
  one number.

## B. Example watchlists seeded
New users (and existing users who haven't created them yet) land with
THREE additional example watchlists alongside Core Winners — so
dropdowns everywhere actually have variety.
- web/src/lib/watchlists.ts — EXAMPLE_WATCHLISTS array +
  seedExampleWatchlists(userId) helper. Idempotent: only inserts a
  list with a name not already present.
- The four pages that already call getOrSeedDefaultWatchlist now also
  call seedExampleWatchlists: watchlists, patterns, backtest,
  simulation. So the first time a user visits any of them, they end
  up with: Core Winners (Mike's seed), Dividend ETFs · Examples
  (SCHD/JEPI/JEPQ/VYM/FEPI/NVDY/QYLD), Mega-Cap Swing · Examples
  (AAPL/MSFT/GOOGL/AMZN/NVDA/META/TSLA), Crypto Core · Examples
  (BTC/ETH/SOL/XRP).
- Watchlist dropdowns on Backtest and Simulation Lab now show all
  four; users can promote / edit / delete from there.

## C. Live wheel pricing (the recommended first options step)
The Wheel page was showing modeled Black-Scholes premiums only. The
agents service already had get_option_contracts / get_option_quote /
live_option_pick — they just weren't surfaced.
- agents/app/main.py — new GET /wheel/live-quotes?underlyings=...
  endpoint. Per symbol: fetch spot, compute 5%-below + 5%-above
  strikes, look up the nearest listed contract ~30 DTE, return live
  CSP + CC premium with the real OCC symbol and expiration.
- web/src/components/dashboard/wheel-live-quotes.tsx (new) — server
  component that calls the endpoint and renders a "Live wheel
  pricing" table above the per-underlying cycle cards. Shows spot,
  CSP strike + premium (×100 per contract), CC strike + premium.
- web/src/app/dashboard/wheel/page.tsx — wires the new panel above
  the cycle cards. Modeled prices below remain as the planner; live
  is the reality check before a real order goes out.
- Graceful: if Alpaca isn't configured, the panel renders a dashed
  card explaining what to set up. If a particular symbol has no live
  quote, the row says so and the modeled price keeps working.

## What this opens up (still queued)
- Wire submit_bracket_order for options through trade_execution so
  the Wheel can place real paper-options orders (using the per-user
  OAuth token path we just shipped).
- Read the user's options approval level from
  /v2/account/configurations and surface it on Settings → Live
  Trading + the Wheel page. Add it to the go-live checklist:
  "Approved for at least Options Level 1 with Alpaca."

## Verified
All 8 touched / new files compile / balance.
