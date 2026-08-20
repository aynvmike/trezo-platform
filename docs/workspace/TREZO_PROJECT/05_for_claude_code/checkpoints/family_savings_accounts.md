# Family & savings accounts

Date: 2026-05-23
Status: COMPLETE (chunk 1 of 3 from the feedback batch)

The user wanted the account types that fit a child's KINDRIP account
surfaced, more savings accounts researched and added, and AI-style
example picks shown.

## Built

- **web/src/lib/tax-strategy.ts** — the account knowledge expanded from
  5 to 9. Added four savings accounts, with a focus on family/child use:
  Series I savings bonds (I-bonds), Coverdell ESA, Custodial Roth IRA,
  and a custodial brokerage account (UTMA / UGMA). Each AccountInfo now
  carries an `audience` ("family" / "individual" / "both") and a worked,
  plain-language `example` (e.g. "$200 a month from birth at ~7% could
  reach ~$86,000 by age 18"). New `familyAccounts()` helper returns the
  child-relevant set.

- **KINDRIP page** — new "Accounts for a child's wealth" section: every
  family/both account as a collapsible card with its what / why / facts
  / worked example. Directly answers "show the account types that apply
  to a child", framed as education, not advice.

- **Tax page** — each tax-advantaged account card now shows its worked
  example too.

The "examples the AI would add" are delivered as solid worked examples
baked into every account — illustrative and clearly labelled estimates,
consistent with how Trezo presents all educational content.

## Verification

- tax-strategy.ts: brace/paren/bracket-balanced; one
  TAX_ADVANTAGED_ACCOUNTS declaration; 9 accounts; familyAccounts()
  present. (An earlier slice bug that duplicated the array was caught
  and the file fully rewritten clean.)
- kindrip/page.tsx + _tax-strategy-section.tsx balanced.

## Still queued (chunks 2 & 3)

Paper Trading interactivity + a Live Trading section; the strategy
library horizontal carousel.

## User-side steps

- No migration. Restart the web app.
