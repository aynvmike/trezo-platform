# Phase 9.5 — Tax Strategy & Tax-Advantaged Accounts — COMPLETE

Completed 2026-05-22. Slotted between Phase 9 (KINDRIP) and Phase 10
(live brokerage). The Tax Optimizer grew from a bill estimator into a
tax-strategy advisor: it now explains the tax-advantaged accounts and
money-saving moves a Trezo user can use, in plain language and with the
math, framed as education — never personalized advice.

## Sub-phases

### 9.5a — Tax Strategy core
- `web/src/lib/tax-strategy.ts` — the knowledge + math module.
- Migration `0018_tax_strategy.sql` — adds `employer_match_pct`,
  `employer_match_cap_pct`, `retirement_contribution_pct` to `profiles`.

### 9.5b — Onboarding step + Tax page strategy section
- `tax-strategy.ts` expanded: five tax-advantaged accounts (employer
  retirement, Roth IRA, HSA, 529 college-savings plan, Future Index
  Account), a ten-item `TAX_STRATEGIES` list (capture the match,
  long-term holding, loss harvesting, wash-sale rule, qualified
  dividends, asset location, 529, withholding, Roth diversification,
  gifting appreciated shares), and `GLIDE_PATH_STAGES`.
- Onboarding Tax step gained an optional "Finding your tax savings"
  panel — annual income, retirement-plan contribution %, employer match
  rate %, and match cap %. All optional; blank boxes are skipped.
- New `web/src/app/dashboard/tax/_tax-strategy-section.tsx` — a server
  component rendering accounts, the employer-match "free money" math, a
  withholding note, the strategies, and the age-based glide path.
- Profile settings form + `_actions.ts` extended with five tax fields
  (annual income, state tax rate, retirement %, match %, match cap %)
  so they are editable after onboarding.
- KINDRIP `agents/app/kindrip/allocation.py` rebuilt: the Auto mix is
  now a smooth 529-style age glide path — ~92% stocks at birth gliding
  to ~20% by age 18, the rest moving into bonds and cash. Added
  `stock_pct_for_age`, `glide_mix`, `glide_explanation`. Replaces the
  four discrete age buckets.

### 9.5c — KINDRIP-Tax link + agent extension
- Tax page now queries `kindrip_children` / `kindrip_transactions` and
  shows a "Child accounts (KINDRIP)" card: dollars moved into child
  accounts year-to-date, total contributed, and a plain-language note —
  this money leaves the taxable trading balance and grows tax-advantaged
  inside the Future Index Account. New `childAccountTaxNote()` helper.
- KINDRIP page gained a short line explaining the tax treatment of a
  contribution, linking to the Tax page.
- Tax Optimizer agent (`agents/app/agents/tax_optimizer.py`) extended:
  alongside the setaside nudge it now emits an `employer_match_gap`
  message when match money is left unclaimed, and a `child_accounts`
  message summarising tax-advantaged child-account contributions.
  Added `_match_left_on_table()` (mirrors `employerMatchValue` in TS).

## Adjustable consecutive-loss limit (built alongside 9.5)

- Migration `0019_loss_limit_setting.sql` — adds
  `consecutive_loss_limit` (int, default 3, range 2-10) to
  `bot_settings`.
- `agents/app/runtime/settings.py` and `agents/app/paper/killswitch.py`
  read it; the kill-switch pauses the day at the user's chosen number
  of losses in a row, not a hardcoded 3.
- Bot Tuning has a "Losing-streak limit" slider (conservative ~3,
  aggressive ~7) so an aggressive strategy is not cut off mid-job
  during a normal losing streak.

## What the user needs to do

1. Apply migrations `0018_tax_strategy.sql` and
   `0019_loss_limit_setting.sql` in Supabase.
2. Restart the agents (`nuke-agent-cache.bat`) — agent count stays 15.
3. Restart the web app. The Tax page now has a Tax Strategy section;
   onboarding and Profile settings have the tax-strategy fields; Bot
   Tuning has the Losing-streak limit slider.

## Verification

- All web files brace/paren-balanced, zero null bytes.
- Onboarding and profile form fields matched to their Zod schemas.
- KINDRIP glide path checked across ages 0-25 (weights sum to 1.0).
- Employer-match math checked against five cases (e.g. $60k / 3% / 50%
  match / 6% cap -> $900 captured, $900 left on the table).
- All 65 agent files parse clean (ast sweep).

## Known limitations / deferred

- Tax content is educational only — accounts, the math, and strategies.
  No personalized "you should" advice, by design.
- Brackets and contribution limits are approximate and dated (2025);
  they need a yearly refresh.
- State 529 deductions/credits vary by state and are described
  generally, not computed per state.
- The withholding set-aside uses a 25% rule-of-thumb on the Tax page;
  it is not yet a saved per-user preference.

## Next phase

- **Task #108 — verification pass:** agent/tool accuracy scan,
  authentication security review, and a sitemap.
- **Phase 10: live brokerage** — real-money execution.
