# Phase 14 — KINDRIP projections & tax-savings

Date: 2026-05-23
Status: COMPLETE

The user wanted the KINDRIP page to be more than the Future Index
Account info box — a projection of where a child's account could sit at
age 18, a tax-savings figure as an incentive, and a personalised feel
that stays current as the years pass.

## Built

- **web/src/lib/kindrip-projection.ts** — a projection engine. From the
  child's current balance and a monthly contribution it compounds
  month-by-month to age 18. Three market assumptions (conservative 5%,
  expected 7%, strong 9%). `summarize()` also runs a taxable-account
  comparison (same contributions, a ~0.8%/yr tax drag) and returns the
  gap at 18 as the estimated tax advantage.

- **_kindrip-projection.tsx** — a per-child projection panel:
  - An editable monthly-contribution input (pre-filled from the child's
    real contribution setting) and a market-assumption switch.
  - An SVG chart: the projected value curve as a filled area, with a
    dashed "what you put in" line beneath — the gap is the growth.
  - A summary: value at 18, total you add, growth on top.
  - A tax-advantage panel: the estimated dollars the Future Index
    Account beats a taxable account by, clearly labelled an estimate,
    with a link to the Tax page.
  - Personalised + always-current: it re-anchors on today's live
    account value and the real remaining years every time the page
    loads, so it stays accurate as the child grows.

- **kindrip/page.tsx** — childSection computes a sensible default
  monthly contribution from the child's settings and renders the
  projection panel between the quarter card and the holdings table.

## Edge cases

- No birth year set → a prompt to set it (no projection possible).
- Child already 18 → a "growth phase complete" note instead of a chart.
- Percent-mode contributions vary, so the default seeds at $100 and the
  user adjusts the input.

## Verification

- kindrip-projection.ts, _kindrip-projection.tsx, page.tsx all
  brace/paren/bracket-balanced.
- React hooks are called unconditionally before the age-guard returns.
- No node_modules in the sandbox — no tsc run.

## User-side steps

- No migration. Restart the web app. Each child on the KINDRIP page now
  shows a projection to 18 with the tax-advantage estimate.
