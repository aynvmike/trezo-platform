-- =====================================================================
-- Trezo — Dividend DRIP
--
-- Lets a dividend holding reinvest its own distributions, so the
-- position compounds — the same compounding KINDRIP gives a child's
-- account, here for the user's own Dividends layer.
-- Safe to re-run.
-- =====================================================================

alter table public.user_positions
  add column if not exists drip_enabled boolean not null default true;

alter table public.user_positions
  add column if not exists dist_yield_pct numeric(6, 2) not null default 0
  check (dist_yield_pct >= 0 and dist_yield_pct <= 500);

alter table public.user_positions
  add column if not exists last_distribution_date date;

-- Seed an estimated annual distribution yield for the YieldMax holdings
-- so DRIP has something to model from day one. These option-income ETFs
-- genuinely run high; the user can tune each one on the Dividends page.
update public.user_positions
  set dist_yield_pct = 40
  where asset_type = 'yieldmax' and dist_yield_pct = 0;
