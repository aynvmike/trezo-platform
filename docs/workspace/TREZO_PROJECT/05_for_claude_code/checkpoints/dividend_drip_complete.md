# Dividend DRIP — COMPLETE

Completed 2026-05-22. Mike's ask: users who invest in the Dividends
layer should get the same compounding KINDRIP gives a child's account —
by reinvesting their distributions back into the same holdings. For
users with no children, this is their compounding engine.

## What was built

- **Migration 0021** — `user_positions` gains `drip_enabled` (default
  true), `dist_yield_pct` (estimated annual distribution yield), and
  `last_distribution_date`. Seeds a 40% yield on the YieldMax holdings
  so DRIP models out of the box.
- **`agents/app/dividends/drip.py`** — the reinvestment engine: weekly
  distribution cadence, `period_distribution(value, yield)`, and a
  plain-language explanation builder.
- **`agents/app/agents/dividend_manager.py`** — the 16th agent. Every
  6 hours it walks dividend holdings; for each whose weekly
  distribution is due it credits a modeled distribution and, with DRIP
  on, buys more shares (the position compounds); with DRIP off it banks
  the cash in `cumulative_dist`. Registered in bootstrap (count = 16).
- **Dividends page** — the YieldMax tracker now shows distributions to
  date and a per-holding DRIP control: an on/off toggle and an editable
  estimated yield, saved via `_actions.ts` (`saveDripSettings`).

Modeled / paper, like the rest of Trezo.

## Spending-comparison generalisation (same session)

Budget Mirror's fixed "car vs. apps" panel was generalised into a
customizable **Spending comparison**: pick a preset (rideshare vs. car,
coffee out vs. brewing at home, ATM fees vs. paying direct) or go fully
custom — enter what you spend now vs. the cheaper way, and it shows the
monthly and yearly amount freed up. The spend side can be filled from
the user's uploaded data.

## What the user needs to do

1. Apply migration `0021_dividend_drip.sql` in Supabase.
2. Restart the agents (count = 16) and the web app.

## Verification

All 16 agent files parse clean; 16 agent classes = 16 registered. Web
files brace-balanced, no null bytes. DRIP distribution math checked
($450 position at 40% yield -> ~$3.46/week, reinvested into shares).
