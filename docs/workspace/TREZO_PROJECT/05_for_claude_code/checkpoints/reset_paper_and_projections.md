# Checkpoint — Reset paper account + Future Projections

Date: 2026-05-26

## 1. Reset paper account to a target equity
A quick win so Mike can test the bot at $1k / $5k / $10k / $25k / $100k
without leaving the dashboard.
- web/src/app/api/paper/reset/route.ts (new) — POST { target_equity_usd }
  closes every open paper position (status -> closed_manual, P&L 0),
  resets the paper_accounts row (starting_capital, cash, vault, YTD &
  today P&L, daily_target_hit_today, last_reset_date), and logs a
  vault_transactions row with kind="reset" for the audit trail.
- web/src/components/dashboard/account-size-sim.tsx (new) — preset
  chips $1k/$5k/$10k/$25k/$100k + custom input + a confirm step.
- web/src/app/dashboard/paper/page.tsx — wired the component in just
  above the Open positions section.

How it adapts the agents: nothing else needs to be told. The allocation
posture map reads the new equity automatically (growth / balanced /
income tilt by account size), so Mike sees the agents recalibrate on
the very next tick.

## 2. Future Projections — every account side by side
A long-horizon "what-if" workbench so the user can see how each account
type fares over 10/20/30 years, factoring tax drag.
- web/src/app/dashboard/projections/page.tsx (new) — server page.
- web/src/app/dashboard/projections/_projections-lab.tsx (new) —
  interactive client component.
- web/src/components/dashboard/nav-config.ts — added Future Projections
  to the core sidebar group (next to Budget Mirror).

Inputs: starting balance, monthly add, expected return, time horizon,
ordinary-income bracket, long-term-gains rate.

What-if toggles: tax-loss harvesting on taxable; donate appreciated
shares (% of end gains) directly to charity.

Accounts modeled (5):
  - Taxable brokerage    — yearly drag + LTCG at sale
  - Roth IRA             — pay tax now, grow & withdraw tax-free
  - Traditional IRA/401k — pre-tax in, ordinary-income on withdrawal
  - Future Index Account — Trezo's name for the OBBB child wrapper
  - Deferred annuity     — tax-deferred growth, ord-income on gains

Output:
  - Single chart with 5 lines (after-tax balance over time).
  - 5 account cards with end balance + delta vs taxable + plain-words
    explanation of how taxes work for that account.
  - Insight banner naming the top pick and the tax-wrapper edge.

## Verified
All 6 touched / new files balanced 0/0/0.

## Still queued
- Alpaca Live wiring + go-live checklist (kept for last per Mike's
  ordering).
- Simulation Lab — fast-forward backtest-driven week with all agents.
- (Skipped for now: IBKR connector.)
