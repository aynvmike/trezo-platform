# Checkpoint — Alpaca-synced KPI tiles + auth notes

Date: 2026-05-26

## What changed
- web/src/lib/alpaca-snapshot.ts (new) — shared server-side fetcher
  for /paper/alpaca-snapshot. Next.js dedupes inside one request so
  the Paper page calls it once and both the KPI overrides and the
  AlpacaSnapshot detail panel use the same data.
- web/src/app/dashboard/paper/page.tsx
  - Fetches the Alpaca snapshot server-side.
  - When Alpaca is configured + reachable, the Cash and Today P&L
    tiles read from Alpaca (a.cash and a.equity - a.last_equity);
    label flips to "Cash · Alpaca" and "Today's P&L · Alpaca".
  - Vault and YTD stay Trezo-internal (they're not Alpaca concepts).
  - Adds a tiny beginner-only caption under the tiles explaining the
    split.
- web/src/components/dashboard/alpaca-snapshot.tsx
  - No longer duplicates Equity / Cash / Today-P&L tiles — those move
    into the page's KPI section.
  - Now focuses on Buying power, Open P&L, Day-trades used, and the
    open-positions table — the detail you don't get from the KPIs.

## Outcome
Mike's screenshot showed Trezo's cash $5,000 next to Alpaca's equity
$100,056 — the dashboard contradicted itself. Now: the Paper Trading
page reads Alpaca for cash and today's P&L; everywhere on the page
shows the same number; the AlpacaSnapshot panel below adds buying
power, day-trade count, and the full positions table for detail.

## Verified
All 3 web files balanced.

## Open follow-up: per-user / OAuth onboarding
Today Alpaca is a single-process env var (ALPACA_API_KEY /
ALPACA_SECRET_KEY). For multi-user beta + a "log in to Alpaca instead
of pasting keys" experience, the right build is:
  - Add a `broker_connections` table (user_id, broker, encrypted
    access_token + refresh_token, status, expires_at).
  - Implement Alpaca OAuth — Alpaca Connect endpoint produces an
    authorization URL; user signs in on Alpaca; redirect back with a
    token; encrypt + persist.
  - When the agents service routes a trade, it picks the per-user
    token from broker_connections via the user_id on the signal.
  - Encryption uses the existing FERNET_ENCRYPTION_KEY.
This is the right next build for the beta-tester rollout.
