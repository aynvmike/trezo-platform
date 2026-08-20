# Phase 9 — KINDRIP (Layer 7) — COMPLETE

> Built by Nova, 2026-05-22.

KINDRIP is the innermost protection ring — generational wealth.
"KIN" (kindred) + "DRIP" (Dividend Reinvestment Plan): a recurring
contribution the parent sets is routed into a child's portfolio, which
auto-invests into a steady index mix. Built in three parts. All modeled
(paper), like the rest of Trezo.

## What shipped

### 9a — Schema + allocation model
- Migration `0017` — three tables: `kindrip_children` (a parent-managed
  child profile + contribution rule + allocation weights + balances),
  `kindrip_holdings` (the child's ETF positions), `kindrip_transactions`
  (the deposit/invest/seed log, each row with a plain-language note).
- `agents/app/kindrip/allocation.py` — the mix logic. **Auto** mode lets
  the AI pick an age-appropriate mix (growth-heavy for a young child,
  bond-heavy as college nears); **Custom** mode lets the parent set the
  four SCHD / VTI / BND / cash weights by hand.

### 9b — Contribution + auto-invest engine
- `agents/app/kindrip/engine.py` — for each child whose contribution is
  due (weekly = 7+ days, monthly = 28+), it moves the configured amount
  (a fixed dollar figure, or a percent of the parent's paper cash) from
  the parent into the child, applies the one-time **$1,000 federal seed**
  once OBBB funding opens (2026-07-04), auto-invests across the mix at
  modeled SCHD/VTI/BND prices, and logs every move with a kid-friendly
  explanation.
- `agents/app/agents/kindrip_agent.py` — the **15th agent**, ticking
  every 6 hours. Registered in bootstrap (count = 15).

### 9c — Web UI + nav
- New page **`/dashboard/kindrip`** — add a child, see each child's
  portfolio (account value, holdings, total contributed, federal-seed
  status), set the contribution rule (fixed/percent, weekly/monthly,
  on/off) and the allocation (Auto/Custom + four weights), and read the
  deposit history with its plain-language explanations.
- The page leads with the Future Index Account explainer (the $1,000
  seed, the $5,000/year cap, the 2026-07-04 funding date, the
  invest-until-18 rule) — framed as information, not advice.
- Sidebar: Layer 7 "KINDRIP" is no longer greyed out.

## Decisions made (worth remembering)

1. **A child is a parent-managed record, not a separate login.** The
   spec's `kindrip_links` (child as its own user) is superseded — a
   child logging in at 18 is a later concern.
2. **Funding is a recurring contribution the parent sets** — a fixed
   amount or a percent of paper cash, weekly or monthly — not a slice of
   profits. (Mike's call; it overrides the spec's profit-routing.)
3. **The $1,000 federal seed is date-gated.** By law the OBBB account
   cannot be funded before 2026-07-04; the engine withholds the seed
   until then and applies it automatically.
4. **"Future Index Account," never "Trump Accounts"** in the UI — the
   law is referenced so users can connect the dots.

## What the user needs to do

1. Apply migration `db/migrations/0017_kindrip.sql` in Supabase (done).
2. Restart the agents (`nuke-agent-cache.bat`) — the bootstrap line
   should read **`count=15`**.
3. Restart the web app. New page: **KINDRIP** (Layer 7 in the sidebar).

## Known limitations / deferred

- Holdings are valued at cost basis in the web page (no live ETF price
  feed on the web side). A live-price valuation can use the same data
  source the agents use.
- The $5,000/year contribution cap is shown as guidance, not hard-enforced.
- Quarterly child-portfolio reports (a spec nice-to-have) are not built.
- Still single-user; per-user runtime is the Phase 5b deferral.

## Next phase

- **Phase 10: live brokerage** — real-money execution (Alpaca live, and
  the real Future Index / custodial accounts).
