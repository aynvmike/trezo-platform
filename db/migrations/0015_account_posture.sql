-- =====================================================================
-- Trezo — Phase 8a.2: account posture & capital allocation overrides
--
-- account_posture:      'auto' lets the AI pick the posture from account
--                       size; growth/balanced/income force a posture.
-- allocation_overrides: optional {market_type: dollar_budget} the user
--                       sets by hand; an empty object means "AI decides".
-- =====================================================================

alter table public.bot_settings
  add column if not exists account_posture text not null default 'auto'
  check (account_posture in ('auto', 'growth', 'balanced', 'income'));

alter table public.bot_settings
  add column if not exists allocation_overrides jsonb not null default '{}'::jsonb;
