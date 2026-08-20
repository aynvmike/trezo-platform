# Paper page build fix · Live Trading copy

Date: 2026-05-24
Status: COMPLETE

## Build error — fixed (was blocking /dashboard/paper)

The Paper Trading page would not compile: "Unexpected token `div`".
Cause: an earlier edit's file write was truncated partway through the
KPI component (a known C:\Trezo write hazard — see the file-writing
note), leaving the file ending mid-tag at `<p className="text-xs
uppercase tr`. Rebuilt the missing KPI tail (the label / value
paragraphs and the closing tags). The file now balances and compiles.

Lesson re-applied: after any C:\Trezo write, a brace/paren imbalance is
a TRUNCATION signal — not noise — and must be chased down, not
dismissed.

## Live Trading page — copy cleaned

The go-live steps named internal details a user should not see — env
var names (ALPACA_LIVE_API_KEY) and file paths (agents/.env,
GO_LIVE_CHECKLIST.md). Reworded to plain user-facing milestones: run in
paper, complete the safety review, connect a funded live account,
switch live on.

## Queued from the same feedback batch

- Backtest a whole watchlist, not one ticker at a time.
- Help search should answer a typed question (AI), not just filter.
- Dividend Wheel: show the cycle state (put / waiting / assigned /
  covered call), account for dividend + securities-lending (FPSL)
  income, add a beginner cycle explainer.
- Future projections for every account (not just KINDRIP), factoring in
  taxes and tax-saving / donation effects — possibly its own section.

## User-side steps

- No migration. Restart the web app — /dashboard/paper compiles again.
