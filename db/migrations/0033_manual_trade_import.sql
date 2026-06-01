-- =====================================================================
-- Trezo — Phase 13/14 follow-up: manual trade history import
-- =====================================================================
-- Lets Mike paste / upload his own real trade history into the
-- learning ledger so the bot's suggestions reflect his actual market
-- experience, not just the paper-trading subset.
--
-- Adds 'manual_import' to the source_table check constraint and lets
-- the user INSERT their own rows (RLS rule). The recorder still owns
-- 'paper_positions' / 'options_positions' inserts via service role;
-- this rule covers the user-driven CSV path.
-- =====================================================================

-- Relax the source_table check to permit manual entries.
alter table public.trade_outcomes
  drop constraint if exists trade_outcomes_source_table_check;

alter table public.trade_outcomes
  add constraint trade_outcomes_source_table_check
  check (source_table in ('paper_positions', 'options_positions', 'manual_import')
         or source_table is null);

-- RLS — allow the user to INSERT their own rows (must match user_id).
drop policy if exists trade_outcomes_self_insert on public.trade_outcomes;
create policy trade_outcomes_self_insert on public.trade_outcomes
  for insert with check (auth.uid() = user_id);

-- Also let the user DELETE their own manual rows (useful to undo a
-- bad CSV paste). Auto-recorded rows from paper closes can also be
-- deleted by the owner — these are the user's own learning data, not
-- a system-of-record audit trail.
drop policy if exists trade_outcomes_self_delete on public.trade_outcomes;
create policy trade_outcomes_self_delete on public.trade_outcomes
  for delete using (auth.uid() = user_id);

comment on constraint trade_outcomes_source_table_check on public.trade_outcomes is
  'Manual imports use source_table=manual_import; bot-recorded rows use paper_positions or options_positions.';
