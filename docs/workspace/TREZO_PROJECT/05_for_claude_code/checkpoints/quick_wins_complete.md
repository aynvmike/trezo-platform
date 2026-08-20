# Quick-Wins Cleanup Batch — COMPLETE

Completed 2026-05-22. Seven deferred items from past phases, picked from
DEFERRED_ITEMS_TRACKER.md and built in one batch at Mike's request.

## What was built

- **QW1 — Manual close-position button.** A "Close now" button on each
  open paper position (/dashboard/paper). Sets `close_requested`; the
  Position Monitor closes it at the current price on its next tick.
  Alpaca-broker positions show "broker-managed" (the bracket handles them).
- **QW2 — KINDRIP $5,000/year cap hard-enforced.** The contribution
  engine now caps a contribution at the annual room remaining; the
  one-time federal seed does not count. Trimmed contributions carry a
  plain-language explanation.
- **QW3 — Withholding set-aside % is a saved preference.** Replaces the
  fixed 25% rule of thumb; editable in Profile settings, read by the
  Tax page.
- **QW4 — Approve/dismiss buttons for Suggest-mode scope changes.** On
  the Strategy page; approving flips a suggestion to 'applied' and the
  Adaptive Scope agent loads it into the live scope on its next tick.
- **QW5 — Live ETF valuation on the KINDRIP page.** Child holdings show
  live market value and gain (Finnhub quotes), falling back to cost
  basis per holding when a quote is unavailable.
- **QW6 — Per-coin crypto daily loss limit.** A coin is benched for the
  rest of the UTC day once its realized loss reaches 10% of its slice
  of the crypto allocation budget. Enforced by the Risk Manager.
- **QW7 — Footer legal links + watchlist drag-drop.** New /privacy,
  /terms, /contact pages (the footer links were dead). The watchlist
  detail list now supports native drag-and-drop reordering.

## Migration

- `db/migrations/0020_quick_wins.sql` — `paper_positions.close_requested`,
  `profiles.withholding_set_aside_pct`, and an UPDATE RLS policy on
  `strategy_scope_adjustments` (so an authenticated user can approve a
  suggestion). One migration covers QW1, QW3, QW4.

## What the user needs to do

1. Apply `db/migrations/0020_quick_wins.sql` in Supabase.
2. Restart the agents and the web app.

## Deferred items now visible in the task list

The remaining open items from DEFERRED_ITEMS_TRACKER.md were added to the
task list as eight "Backlog —" tasks, so not-done work is visible in the
progress view rather than buried in checkpoints:

- Per-user / multi-user runtime (Phase 5b)
- LLM sentiment + NeMo Guardrails (Phase 5b)
- Backtest framework
- Options engine — remaining strategies & integrations
- Strategy-specific scoring models
- Quarterly KINDRIP child-portfolio reports
- Live/premium market-data feed (unblocks several filters)
- Annual tax-figures refresh

## Verification

- All seven build areas verified — web files brace/paren-balanced, zero
  null bytes; all agent files parse clean.
- KINDRIP cap, glide-path, and employer-match math spot-checked.
