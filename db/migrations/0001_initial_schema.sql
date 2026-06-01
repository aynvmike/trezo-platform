-- =====================================================================
-- Trezo — Initial Schema (Phase 0)
-- Run this in the Supabase SQL editor (or via supabase db push).
-- =====================================================================

-- --------------------------------------------------------------------
-- profiles — extends auth.users with Trezo-specific fields
-- --------------------------------------------------------------------
create table if not exists public.profiles (
  user_id                   uuid primary key references auth.users(id) on delete cascade,
  display_name              text,
  stock_capital_usd         numeric(14, 2) default 0 check (stock_capital_usd >= 0),
  crypto_capital_usd        numeric(14, 2) default 0 check (crypto_capital_usd >= 0),
  options_capital_usd       numeric(14, 2) default 0 check (options_capital_usd >= 0),
  risk_tolerance            text check (risk_tolerance in ('conservative', 'balanced', 'aggressive')),
  daily_profit_target_usd   numeric(14, 2) default 0 check (daily_profit_target_usd >= 0),
  tax_filing_status         text check (tax_filing_status in ('single', 'married_joint', 'married_separate', 'head_of_household')),
  ethical_filters_enabled   boolean not null default true,
  onboarding_complete       boolean not null default false,
  created_at                timestamptz not null default now(),
  updated_at                timestamptz not null default now()
);

create index if not exists profiles_updated_at_idx on public.profiles(updated_at desc);

-- --------------------------------------------------------------------
-- watchlists & watchlist_items
-- --------------------------------------------------------------------
create table if not exists public.watchlists (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references auth.users(id) on delete cascade,
  name        text not null,
  is_default  boolean not null default false,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  unique (user_id, name)
);

create table if not exists public.watchlist_items (
  id            uuid primary key default gen_random_uuid(),
  watchlist_id  uuid not null references public.watchlists(id) on delete cascade,
  ticker        text not null,
  asset_type    text not null check (asset_type in ('stock', 'crypto', 'option')),
  notes         text,
  starred       boolean not null default false,
  position      integer not null default 0,
  created_at    timestamptz not null default now(),
  unique (watchlist_id, ticker)
);

create index if not exists watchlist_items_watchlist_idx on public.watchlist_items(watchlist_id, position);

-- --------------------------------------------------------------------
-- trades — immutable ledger (paper + real). Append-only.
-- --------------------------------------------------------------------
create table if not exists public.trades (
  id                uuid primary key default gen_random_uuid(),
  user_id           uuid not null references auth.users(id) on delete cascade,
  asset_type        text not null check (asset_type in ('stock', 'crypto', 'option')),
  ticker            text not null,
  side              text not null check (side in ('buy', 'sell', 'short', 'cover')),
  quantity          numeric(20, 8) not null check (quantity > 0),
  price             numeric(20, 8) not null check (price >= 0),
  fees              numeric(14, 4) not null default 0,
  is_paper          boolean not null default true,
  broker            text,
  broker_order_id   text,
  strategy          text,
  reasoning         jsonb,
  executed_at       timestamptz not null default now(),
  created_at        timestamptz not null default now()
);

create index if not exists trades_user_executed_idx on public.trades(user_id, executed_at desc);
create index if not exists trades_user_ticker_idx on public.trades(user_id, ticker);

-- --------------------------------------------------------------------
-- agent_logs — every agent decision with reasoning
-- --------------------------------------------------------------------
create table if not exists public.agent_logs (
  id           bigserial primary key,
  user_id      uuid references auth.users(id) on delete cascade,
  agent_name   text not null,
  kind         text not null,  -- signal, veto, alert, error, info
  confidence   numeric(4, 3) check (confidence between 0 and 1),
  payload      jsonb not null default '{}'::jsonb,
  created_at   timestamptz not null default now()
);

create index if not exists agent_logs_user_created_idx on public.agent_logs(user_id, created_at desc);
create index if not exists agent_logs_agent_idx on public.agent_logs(agent_name, created_at desc);

-- --------------------------------------------------------------------
-- kindrip_children — Phase 8 placeholder (schema ready, UI deferred)
-- --------------------------------------------------------------------
create table if not exists public.kindrip_children (
  id           uuid primary key default gen_random_uuid(),
  parent_id    uuid not null references auth.users(id) on delete cascade,
  display_name text not null,
  birth_year   integer check (birth_year between 1900 and 2200),
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

create table if not exists public.kindrip_contributions (
  id           uuid primary key default gen_random_uuid(),
  child_id     uuid not null references public.kindrip_children(id) on delete cascade,
  amount_usd   numeric(14, 2) not null check (amount_usd >= 0),
  allocation   jsonb not null default '{}'::jsonb,
  contributed_at timestamptz not null default now()
);

-- --------------------------------------------------------------------
-- updated_at trigger
-- --------------------------------------------------------------------
create or replace function public.set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists profiles_set_updated_at on public.profiles;
create trigger profiles_set_updated_at
  before update on public.profiles
  for each row execute function public.set_updated_at();

drop trigger if exists watchlists_set_updated_at on public.watchlists;
create trigger watchlists_set_updated_at
  before update on public.watchlists
  for each row execute function public.set_updated_at();

drop trigger if exists kindrip_children_set_updated_at on public.kindrip_children;
create trigger kindrip_children_set_updated_at
  before update on public.kindrip_children
  for each row execute function public.set_updated_at();

-- --------------------------------------------------------------------
-- Auto-create a profile row when a new auth user signs up
-- --------------------------------------------------------------------
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer as $$
begin
  insert into public.profiles (user_id) values (new.id)
  on conflict (user_id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();
