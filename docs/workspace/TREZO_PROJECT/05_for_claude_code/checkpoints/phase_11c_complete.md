# Phase 11c — Budget Mirror goals, car comparison, routing — COMPLETE

Completed 2026-05-22. The final part of Budget Mirror. With 11c done,
Phase 11 (Budget Mirror) is complete.

## What was built

`web/src/app/dashboard/budget/_planner.tsx` — a client component below
the simulator on /dashboard/budget:

- **Goal planner** — set a goal name, target amount, and a monthly
  set-aside; it shows months to reach, the completion month, and a
  weekly target.
- **Savings routing** — a destination picker with THREE options:
  the main trading account, a KINDRIP child account, or a standalone
  savings goal (Mike's 2026-05-22 ask — main account included). Each
  destination gives a tailored plain-language note and a link into the
  relevant Trezo page.
- **Car vs. apps** — enter an all-in monthly car cost; it compares
  against the user's rideshare + food-delivery spend from the upload
  and shows the monthly difference and the break-even point.

Wired into `_budget-mirror.tsx` — renders after the simulator once a
file is analysed.

## What the user needs to do

Restart the web app. No migration.

## Phase 11 (Budget Mirror) — complete

- 11a: upload + parse + spending dashboard + data-export guide.
- 11b: fee, frequency, and replacement-cost simulators.
- 11c: goal planner, savings routing (3 destinations), car comparison.

Still client-side and privacy-first throughout — uploaded files are
read in the browser and never stored. Functional auto-wiring of a
recurring contribution into KINDRIP / the account (vs. the guided
hand-off built here) would be a future enhancement.
