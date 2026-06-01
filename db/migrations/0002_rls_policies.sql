-- =====================================================================
-- Trezo — Row-Level Security policies
-- Default deny; users see only their own rows.
-- =====================================================================

alter table public.profiles            enable row level security;
alter table public.watchlists          enable row level security;
alter table public.watchlist_items     enable row level security;
alter table public.trades              enable row level security;
alter table public.agent_logs          enable row level security;
-- kindrip RLS is owned by migration 0017, which redefined the kindrip
-- tables (user_id, not parent_id). 0002 deliberately leaves them alone.

-- profiles ------------------------------------------------------------
drop policy if exists profiles_self_select on public.profiles;
create policy profiles_self_select on public.profiles
  for select using (auth.uid() = user_id);

drop policy if exists profiles_self_insert on public.profiles;
create policy profiles_self_insert on public.profiles
  for insert with check (auth.uid() = user_id);

drop policy if exists profiles_self_update on public.profiles;
create policy profiles_self_update on public.profiles
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- watchlists ----------------------------------------------------------
drop policy if exists watchlists_self_all on public.watchlists;
create policy watchlists_self_all on public.watchlists
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists watchlist_items_self_all on public.watchlist_items;
create policy watchlist_items_self_all on public.watchlist_items
  for all using (
    exists (
      select 1 from public.watchlists w
      where w.id = watchlist_items.watchlist_id and w.user_id = auth.uid()
    )
  ) with check (
    exists (
      select 1 from public.watchlists w
      where w.id = watchlist_items.watchlist_id and w.user_id = auth.uid()
    )
  );

-- trades --------------------------------------------------------------
drop policy if exists trades_self_select on public.trades;
create policy trades_self_select on public.trades
  for select using (auth.uid() = user_id);

drop policy if exists trades_self_insert on public.trades;
create policy trades_self_insert on public.trades
  for insert with check (auth.uid() = user_id);

-- trades are immutable — no update/delete policy (service role only)

-- agent_logs ----------------------------------------------------------
drop policy if exists agent_logs_self_select on public.agent_logs;
create policy agent_logs_self_select on public.agent_logs
  for select using (auth.uid() = user_id);

-- inserts come from service role (agents service), not end users

-- kindrip RLS + policies live in migration 0017 (the kindrip tables
-- were redefined there). Nothing kindrip-related belongs in 0002.
