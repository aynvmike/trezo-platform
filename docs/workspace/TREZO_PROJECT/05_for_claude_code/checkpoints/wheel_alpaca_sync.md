# Checkpoint — Wheel ↔ Alpaca positions sync

Date: 2026-05-26

## What changed
- agents/app/data/occ.py (new) — parse_occ(symbol) returns OptionPart
  (underlying, expiration ISO, type call/put, strike, occ). Handles
  variable-length roots, 6-digit YYMMDD, 8-digit strike in 1/1000ths.
  Sandbox functional check: AAPL241227C00200000 → AAPL, 2024-12-27,
  call, $200; INTC250117P00020000 → INTC, 2025-01-17, put, $20.
- agents/app/main.py — new GET /wheel/positions?user_id=… endpoint.
  Pulls Alpaca's /v2/positions through the per-user OAuth token when
  the user is connected, env keys as fallback. Filters to options
  legs via OCC parsing + asset_class. Classifies each as:
    wheel_csp     — short put (cash-secured)
    wheel_cc      — short call (covered call)
    long_option   — anything else (rare; surfaced not hidden)
  Equity holdings tagged separately so the page can show shares the
  bot is holding between calls. Tags the response with routed=
  user-oauth | env-keys for the audit trail.
- web/src/components/dashboard/wheel-live-positions.tsx (new) — server
  component that calls /wheel/positions for the signed-in user.
  Renders four stat tiles (CSPs / CCs / Premium at work / Unrealized
  P&L), a positions table grouped CSP-then-CC-then-other, and a small
  equity-holdings table beneath when the user holds shares.
- web/src/app/dashboard/wheel/page.tsx — WheelLivePositions wired
  right below OptionsApprovalCard, above the per-underlying cycle
  cards (the modeled planner). So the page reads top-down: approval
  status → live broker positions → live chain pricing → modeled
  planner. Live above, plan below.

## How the two halves stay coordinated
- The Wheel page now answers two questions:
  1. What does the broker actually hold? (live section, real OCC)
  2. What would the bot do next per name? (planner section, modeled)
- When Alpaca is not connected, the live section is a one-line hint
  pointing at Settings → Connections; the planner below is exactly
  what was there before. Nothing breaks.
- The per-user OAuth path means once a beta tester taps Connect on
  Settings → Connections, the Wheel section on the same account
  reflects their broker — not Trezo's env keys.

## Verified
- occ.py parser unit-checked with 4 inputs (good + bad).
- All touched files compile / balance.

## What's still queued from Mike's recent batch
- Strategy Engine page: explain its purpose + surface an event when
  the agents propose a strategy change.
- Beginner/Pro tone audit: separate educational content from
  operational hints so Pro mode does not gut critical guidance.
