# Phase 11b — Budget Mirror simulators — COMPLETE

Completed 2026-05-22. The behavior simulators for Budget Mirror, on the
/dashboard/budget page below the spending dashboard.

## What was built

`web/src/app/dashboard/budget/_simulator.tsx` — a client component that
takes the uploaded analysis and lets the user model a habit change:

- **Habit picker** — choose a spending category to model.
- **Frequency slider** — keep the habit at 0-100% of its current level.
- **Fee-estimation slider** — the estimated share of each order that is
  fees, service charges, and tips (awareness number).
- **Replacement-cost input** — what the replacement (groceries, gas,
  pickup) costs, so the savings figure stays honest.
- **Result panel** — plain-language read plus gross savings, replacement
  cost, and net savings per month and per year, and the number of
  orders avoided.

Wired into `_budget-mirror.tsx` — it renders below the dashboard once a
file is analysed.

## What the user needs to do

Restart the web app. No migration.

## Next

- 11c — goal planner, car-vs-apps comparison, and routing identified
  savings into Trezo. Per Mike (2026-05-22), the routing destination
  must include the **main trading account**, not only KINDRIP and a
  savings goal.
