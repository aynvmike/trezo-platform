# Dividends holdings fix · paper-trading copy

Date: 2026-05-23
Status: COMPLETE

From the latest feedback round — the blocking bug + a stale-copy fix.
The larger feature requests in the same message are queued separately.

## Dividends holdings — "stuck, can't change anything"

The schema and RLS for user_positions were both fine (a FOR ALL policy,
the unique constraint present), so the cause was not visible by
inspection — but the holdings cards used bare `<form action={...}>`
server actions that returned void and swallowed every Supabase error,
so any failure was silent and looked like a frozen page.

Rebuilt it properly:
- yieldmax/_actions.ts — removeHolding and saveHolding now return
  { ok, error } and actually check the Supabase error.
- yieldmax-tracker.tsx — rebuilt as a robust interactive client
  component: explicit Remove / Save handlers, optimistic updates (a
  removed card disappears at once), per-card "Saving… / Saved ✓ /
  error" feedback. If an operation ever fails now, the user sees why
  instead of a silent freeze.

## Paper Trading — stale copy

Two out-of-date lines fixed: "Real-broker execution lands in Phase 9"
→ "stays off until the go-live checklist is complete"; and the
"strategies come in Phase 6b" line → all strategies are live now.

## Verification

- _actions.ts + yieldmax-tracker.tsx + paper/page.tsx all
  brace/paren-balanced.

## User-side steps

- No migration. Restart the web app. Holdings can now be removed and
  edited with visible feedback.

## Still queued from the same feedback message

Family/child account types on KINDRIP · more savings-account types ·
AI-suggested example picks · strategy-library carousel · Paper Trading
interactivity (quick settings, live backtest + chart) · a dedicated
live-trading section. Grouped into three chunks for sequencing.
