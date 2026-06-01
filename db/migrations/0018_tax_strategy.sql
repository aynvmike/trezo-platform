-- =====================================================================
-- Trezo — Phase 9.5: Tax Strategy — retirement-match profile fields
--
-- Captures what the Tax Strategy advisor needs to show the "free money"
-- math on an employer-matched retirement account. Income + filing status
-- already exist on profiles (Phase 7, migration 0011).
-- =====================================================================

alter table public.profiles
  add column if not exists employer_match_pct numeric(5, 2) not null default 0
  check (employer_match_pct between 0 and 200);

alter table public.profiles
  add column if not exists employer_match_cap_pct numeric(5, 2) not null default 0
  check (employer_match_cap_pct between 0 and 100);

alter table public.profiles
  add column if not exists retirement_contribution_pct numeric(5, 2) not null default 0
  check (retirement_contribution_pct between 0 and 100);
