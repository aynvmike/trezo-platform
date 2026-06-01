-- =====================================================================
-- Trezo — Quick-wins cleanup batch (deferred items from past phases)
--
-- QW1: a manual "close now" flag on paper positions.
-- QW3: a saved withholding set-aside % on profiles.
-- QW4: lets a signed-in user approve / dismiss a suggested scope change.
-- Safe to re-run.
-- =====================================================================

-- QW1 — manual close request. The Position Monitor agent honours this on
-- its next tick and closes the position with reason 'manual'.
alter table public.paper_positions
  add column if not exists close_requested boolean not null default false;

-- QW3 — withholding set-aside %. Replaces the fixed 25% rule of thumb on
-- the Tax page with a saved per-user preference.
alter table public.profiles
  add column if not exists withholding_set_aside_pct numeric(5, 2) not null default 25
  check (withholding_set_aside_pct between 0 and 100);

-- QW4 — Suggest-mode approval. The adjustment log is bot-wide; allow any
-- authenticated user to update a row's status (suggested -> applied /
-- dismissed). Inserts still come from the agents service role.
drop policy if exists scope_adjustments_update on public.strategy_scope_adjustments;
create policy scope_adjustments_update on public.strategy_scope_adjustments
  for update using (auth.role() = 'authenticated')
  with check (auth.role() = 'authenticated');
