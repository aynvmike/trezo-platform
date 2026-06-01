-- =====================================================================
-- Trezo — User positions (Phase 2)
-- Tracks shares the user holds in YieldMax (and any other tracked asset).
-- Distinct from trades (immutable ledger) — this is current holdings.
-- =====================================================================

create table if not exists public.user_positions (
  id              uuid primary key default gen_random_uuid(),
  user_id         uuid not null references auth.users(id) on delete cascade,
  ticker          text not null,
  asset_type      text not null check (asset_type in ('stock', 'crypto', 'option', 'yieldmax')),
  shares          numeric(20, 8) not null check (shares >= 0),
  avg_cost        numeric(20, 8),
  cumulative_dist numeric(14, 4) not null default 0,
  notes           text,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (user_id, ticker, asset_type)
);

create index if not exists user_positions_user_idx on public.user_positions(user_id);

drop trigger if exists user_positions_set_updated_at on public.user_positions;
create trigger user_positions_set_updated_at
  before update on public.user_positions
  for each row execute function public.set_updated_at();

-- RLS — users only see and edit their own positions
alter table public.user_positions enable row level security;

drop policy if exists user_positions_self_all on public.user_positions;
create policy user_positions_self_all on public.user_positions
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
