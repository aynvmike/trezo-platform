# Phase 12e — Budget Mirror audit

Date: 2026-05-23
Status: COMPLETE

Fifth part of the Phase 12 UX overhaul. The user could not find the
spend-vs-save comparison feature and asked whether Budget Mirror has
all its features.

## Finding

The comparison was built (in _planner.tsx) but `_budget-mirror.tsx`
rendered the Simulator and Planner only inside `{analysis && (...)}` —
so with no transactions loaded, the whole lower half of the page,
including the comparison, was invisible. That is why it "could not be
seen".

## Fix

- **_planner.tsx** — its prop `a` is now `BudgetAnalysis | null`. The
  goal planner and the spend-vs-save comparison only used `a` for the
  optional "fill from my uploaded data" helper, so they work fully
  standalone. With no data: months falls back to 1, the rideshare
  preset starts at 0, the fill-from-data dropdown is hidden.
- **_budget-mirror.tsx** — the Planner (goal planner + comparison) now
  renders ALWAYS. The Dashboard and Simulator still need real data, so
  when there are no transactions a NoDataHint explains that uploading
  unlocks them — and that the planner/comparison below already work.
- **_simulator.tsx** — a stale "Coming next" note (promising the
  planner as future work) now points to the planner that exists below.

## On the "agent" question

Budget Mirror has no background agent — by design. It is privacy-first
and fully client-side: the file you give it is parsed in your browser
and never stored or uploaded. The only AI touch is the optional
receipt/PDF scan (Claude vision), and even then the file is not kept.
So "all the features" are present and active without an agent; there
is intentionally no Budget agent reading your spending.

## Verification

- All three edited files brace/paren-balanced.
- No node_modules in the sandbox — no tsc run.

## User-side steps

- No migration. Restart the web app. The goal planner and spend-vs-save
  comparison now appear immediately, before any data is loaded.
