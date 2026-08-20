# Phase 11a — Budget Mirror foundation — COMPLETE

Completed 2026-05-22. The first part of Budget Mirror — a new horizontal
service in Trezo (alongside the Tax Optimizer) that shows a user where
their money goes, so it can be freed up to build wealth in the layers.

Mike's scoping (2026-05-22): build it phased, foundation first; connect
it to Trezo; include a data-export guide for the user.

## What was built

- **`web/src/lib/budget.ts`** — the analysis engine, pure client-side
  functions: a quoted-field CSV parser, smart column detection (date /
  amount / merchant by header keywords), merchant categorisation (Food
  delivery, Rideshare, Groceries, Shopping, Subscriptions, Dining,
  Other), and aggregation (totals, this-month / quarter / YTD,
  per-month average, by-category, by-month, top merchants).
- **`/dashboard/budget`** — the Budget Mirror page.
  - `_budget-mirror.tsx` — a client component: upload a CSV, parsed in
    the browser, with a spending dashboard (KPI tiles, a by-category
    breakdown, a monthly-spending trend, a most-frequent-merchants
    table).
  - `_data-guide.tsx` — the data-export guide: how to download a CSV
    from Uber / Uber Eats, DoorDash, Grubhub, Lyft, Instacart, Amazon,
    and a bank/credit-card statement.
- Nav: "Budget Mirror" added to the core sidebar group.

## Privacy

The uploaded file is read inside the browser to build the view. It is
not uploaded to Trezo, stored, or sent anywhere — privacy-first, matching
the feature brief.

## What the user needs to do

Restart the web app. No migration, no agent change.

## Verification

`budget.ts` logic tested against a sample CSV: quoted fields with commas
parse correctly, "$" amounts parse, and categorisation correctly
separates "Uber Eats" (Food delivery) from "Uber trip" (Rideshare).
All web files brace/paren-balanced, no null bytes.

## Next (Budget Mirror phases)

- 11b — fee-estimation slider, frequency-reduction slider, replacement-
  cost calculator (the behavior simulators).
- 11c — goal-based savings tool, car-vs-apps comparison, and the Trezo
  tie-in: routing identified savings into a KINDRIP contribution, a
  savings goal, or the paper account.
