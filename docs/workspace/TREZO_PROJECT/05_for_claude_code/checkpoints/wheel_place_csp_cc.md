# Checkpoint — Wheel can now place real Alpaca paper options orders

Date: 2026-05-27

## What changed
- agents/app/brokers/alpaca.py — new submit_option_order helper. Same
  signature pattern as submit_bracket_order: optional UserToken arg
  threads per-user OAuth through; supports limit and market orders;
  refuses invalid contracts/sides cleanly.
- agents/app/main.py — new POST /wheel/place-leg endpoint.
  Parameters: user_id, leg (csp|cc), underlying, target_strike,
  target_exp, contracts, optional limit_price. Per-user OAuth token
  first; env keys as fallback. Uses live_option_pick to land on the
  real listed contract closest to the target strike + expiration,
  then submits as sell-to-open. Returns the OCC symbol, Alpaca order
  id and status.

- web/src/app/api/wheel/place-leg/route.ts (new) — auth-gated POST
  that resolves the user id server-side, validates inputs, and
  proxies to the agents endpoint. Validates: leg in {csp, cc},
  underlying ticker regex, ISO date for target_exp, contracts
  clamped 1..50.
- web/src/components/dashboard/wheel-place-button.tsx (new) — client
  button shown per-row inside WheelLiveQuotes. Pattern: idle → tap
  → "Confirm/Cancel" inline → "Placing…" → ✓ Placed (with order
  status) or ✗ Failed (with tooltip error).
- web/src/components/dashboard/wheel-live-quotes.tsx — each premium
  cell now renders the premium amount above and a per-leg
  WheelPlaceButton below. CSP buttons are weave-coloured; CC
  buttons are treasure-coloured.

## How it routes
1. User opens Wheel page → sees the live pricing row for each name.
2. Taps "Place CSP" (or CC) → confirm → POST /api/wheel/place-leg.
3. Web validates + resolves user_id → POST agents /wheel/place-leg.
4. Agents looks up the user's Alpaca OAuth token from broker_
   connections (per-user). If present, the order goes through the
   user's account. If not, falls back to env keys (legacy mode).
5. live_option_pick selects the real listed contract at ~5%-below /
   ~5%-above the spot for that ~30 DTE.
6. submit_option_order sends a sell-to-open limit at the live mid
   premium. Alpaca returns the order id.
7. Button switches to "✓ Placed · <status>"; the Wheel page
   refreshes so WheelLivePositions (Alpaca-fed) picks up the new
   leg on the next load.

## Safety pieces still in force
- The user's options approval level (surfaced by OptionsApprovalCard
  above the live pricing) must be ≥ 1 for Alpaca to fill the order.
  If it's 0, the order will be rejected by Alpaca itself with a
  clear error.
- For LIVE mode, live_trading_enabled() in runtime/trading_mode.py
  remains False — these orders only route to Alpaca paper. The hard
  gate stays in code, not configuration.

## Test-run guidance for today's market
For a quick today's-market run without leaving the dashboard:
  1. Open Simulation Lab.
  2. Watchlist: any of the seeded examples (Mega-Cap Swing,
     Dividend ETFs, Crypto Core) or your Core Winners.
  3. Window: 5d (today's run).
  4. Starting equity: $5,000 (matches your fresh Alpaca paper).
  5. Signal TCS: 650.
  6. Leave "Test every strategy" on.
  7. Tap Replay. The equity curve + by-strategy table populates
     within 30-60 seconds.

## Verified
All 5 touched / new files compile and balance.
