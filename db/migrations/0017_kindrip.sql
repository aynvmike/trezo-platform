-- =====================================================================
-- Trezo — Phase 9: KINDRIP (Layer 7) — children's portfolios
--
-- KINDRIP routes a recurring contribution from the parent into a linked
-- child portfolio that auto-invests into a conservative index mix
-- (SCHD / VTI / BND / cash). The recommended account wrapper is the
-- "Future Index Account" (the OBBB child account). All modeled / paper.
--
-- Safe to re-run: any earlier/partial KINDRIP tables are dropped first.
-- KINDRIP is a brand-new feature with no data depending on it.
-- =====================================================================

drop table if exists public.kindrip_transactions cascade;
drop table if exists public.kindrip_holdings cascade;
drop table if exists public.kindrip_children cascade;
-- kindrip_contributions: an orphaned table from the original 0001
-- sketch (parent_id-based). The live KINDRIP feature uses
-- kindrip_transactions instead. Drop the orphan.
drop table if exists public.kindrip_contributions cascade;

-- A child portfolio the parent manages.
create table public.kindrip_children (
  id                     uuid primary key default gen_random_uuid(),
  user_id                uuid not null references auth.users(id) on delete cascade,
  child_name             text not null,
  birth_year             integer check (birth_year between 2000 and 2100),
  -- Contribution rule (set by the parent)
  contribution_mode      text not null default 'fixed'
    check (contribution_mode in ('fixed', 'percent')),
  contribution_value     numeric(12, 2) not null default 25,
  contribution_cadence   text not null default 'monthly'
    check (contribution_cadence in ('weekly', 'monthly')),
  contribution_enabled   boolean not null default true,
  last_contribution_date date,
  -- Allocation: 'auto' (AI age-based) or 'custom' (parent-set weights)
  allocation_mode        text not null default 'auto'
    check (allocation_mode in ('auto', 'custom')),
  alloc_schd             numeric(5, 4) not null default 0.40,
  alloc_vti              numeric(5, 4) not null default 0.30,
  alloc_bnd              numeric(5, 4) not null default 0.20,
  alloc_cash             numeric(5, 4) not null default 0.10,
  -- Balances
  cash_balance_usd       numeric(14, 2) not null default 0,
  total_contributed_usd  numeric(14, 2) not null default 0,
  federal_seed_applied   boolean not null default false,
  created_at             timestamptz not null default now(),
  updated_at             timestamptz not null default now()
);

create index kindrip_children_user_idx
  on public.kindrip_children(user_id);

-- The child's ETF positions.
create table public.kindrip_holdings (
  id              uuid primary key default gen_random_uuid(),
  child_id        uuid not null references public.kindrip_children(id) on delete cascade,
  symbol          text not null,
  shares          numeric(20, 8) not null default 0,
  cost_basis_usd  numeric(14, 2) not null default 0,
  updated_at      timestamptz not null default now(),
  unique (child_id, symbol)
);

-- The deposit / invest / seed log, each row with a plain-language note.
create table public.kindrip_transactions (
  id           uuid primary key default gen_random_uuid(),
  child_id     uuid not null references public.kindrip_children(id) on delete cascade,
  kind         text not null
    check (kind in ('contribution', 'federal_seed', 'invest')),
  amount_usd   numeric(14, 2) not null default 0,
  symbol       text,
  shares       numeric(20, 8),
  explanation  text not null default '',
  created_at   timestamptz not null default now()
);

create index kindrip_transactions_child_idx
  on public.kindrip_transactions(child_id, created_at desc);

-- updated_at triggers
create trigger kindrip_children_set_updated_at
  before update on public.kindrip_children
  for each row execute function public.set_updated_at();

create trigger kindrip_holdings_set_updated_at
  before update on public.kindrip_holdings
  for each row execute function public.set_updated_at();

-- Row-level security: a parent sees only their own children's records.
alter table public.kindrip_children enable row level security;
alter table public.kindrip_holdings enable row level security;
alter table public.kindrip_transactions enable row level security;

create policy kindrip_children_self on public.kindrip_children
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

create policy kindrip_holdings_self on public.kindrip_holdings
  for select using (child_id in (
    select id from public.kindrip_children where user_id = auth.uid()));

create policy kindrip_transactions_self on public.kindrip_transactions
  for select using (child_id in (
    select id from public.kindrip_children where user_id = auth.uid()));
