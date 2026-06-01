-- =====================================================================
-- Trezo — Phase 7: Tax Optimizer fields
-- =====================================================================

-- Annual ordinary income — used to find the user's marginal bracket so
-- short-term gains stack on top of it correctly.
alter table public.profiles
  add column if not exists annual_income_usd numeric(14, 2) not null default 0
    check (annual_income_usd >= 0);

-- Flat state income-tax rate as a percentage (e.g. 5.0 for 5%).
-- 0 = no state income tax. Encoding every state's brackets is out of scope;
-- a single effective rate the user provides keeps the estimate honest and simple.
alter table public.profiles
  add column if not exists state_tax_rate_pct numeric(5, 2) not null default 0
    check (state_tax_rate_pct >= 0 and state_tax_rate_pct <= 20);
