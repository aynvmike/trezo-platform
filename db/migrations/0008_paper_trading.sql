-- =====================================================================
-- Trezo — Phase 6a: Paper trading foundation
-- =====================================================================

-- ---------------------------------------------------------------------
-- paper_accounts — one row per user. Cash, vault, YTD P&L.
-- ---------------------------------------------------------------------
create table if not exists public.paper_accounts (
  user_id                  uuid primary key references auth.users(id) on delete cascade,
  starting_capital_usd     numeric(14, 2) not null default 0,
  current_cash_usd         numeric(14, 2) not null default 0,
  vault_balance_usd        numeric(14, 2) not null default 0 check (vault_balance_usd >= 0),
  ytd_realized_pnl_usd     numeric(14, 2) not null default 0,
  today_realized_pnl_usd   numeric(14, 2) not null default 0,
  daily_target_hit_today   boolean not null default false,
  last_reset_date          date not null default current_date,
  created_at               timestamptz not null default now(),
  updated_at               timestamptz not null default now()
);

drop trigger if exists paper_accounts_set_updated_at on public.paper_accounts;
create trigger paper_accounts_set_updated_at
  before update on public.paper_accounts
  for each row execute function public.set_updated_at();

alter table public.paper_accounts enable row level security;

drop policy if exists paper_accounts_self_all on public.paper_accounts;
create policy paper_accounts_self_all on public.paper_accounts
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- ---------------------------------------------------------------------
-- paper_positions — open + closed simulated positions
-- ---------------------------------------------------------------------
create table if not exists public.paper_positions (
  id              uuid primary key default gen_random_uuid(),
  user_id         uuid not null references auth.users(id) on delete cascade,
  ticker          text not null,
  asset_type      text not null check (asset_type in ('stock', 'crypto', 'option')),
  side            text not null check (side in ('long', 'short')),
  quantity        numeric(20, 8) not null check (quantity > 0),
  entry_price     numeric(20, 8) not null check (entry_price > 0),
  entry_at        timestamptz not null default now(),
  stop_price      numeric(20, 8),
  target_price    numeric(20, 8),
  -- Lifecycle
  status          text not null default 'open' check (status in ('open', 'closed_stop', 'closed_target', 'closed_manual', 'closed_time', 'closed_eod')),
  exit_price      numeric(20, 8),
  exit_at         timestamptz,
  realized_pnl_usd numeric(14, 4),
  fees_usd        numeric(14, 4) not null default 0,
  -- Provenance
  strategy        text,
  source_payload  jsonb,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create index if not exists paper_positions_user_status_idx on public.paper_positions(user_id, status, entry_at desc);
create index if not exists paper_positions_open_idx on public.paper_positions(user_id) where status = 'open';

drop trigger if exists paper_positions_set_updated_at on public.paper_positions;
create trigger paper_positions_set_updated_at
  before update on public.paper_positions
  for each row execute function public.set_updated_at();

alter table public.paper_positions enable row level security;

drop policy if exists paper_positions_self_all on public.paper_positions;
create policy paper_positions_self_all on public.paper_positions
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- ---------------------------------------------------------------------
-- paper_vault_transactions — audit log of cash <-> vault movements
-- ---------------------------------------------------------------------
create table if not exists public.paper_vault_transactions (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references auth.users(id) on delete cascade,
  amount_usd   numeric(14, 2) not null,         -- positive = into vault, negative = out of vault
  kind         text not null check (kind in ('profit_lock', 'manual_withdrawal', 'manual_deposit', 'reset')),
  description  text,
  created_at   timestamptz not null default now()
);

create index if not exists paper_vault_tx_user_idx on public.paper_vault_transactions(user_id, created_at desc);

alter table public.paper_vault_transactions enable row level security;

drop policy if exists paper_vault_tx_self_select on public.paper_vault_transactions;
create policy paper_vault_tx_self_select on public.paper_vault_transactions
  for select using (auth.uid() = user_id);

drop policy if exists paper_vault_tx_self_insert on public.paper_vault_transactions;
create policy paper_vault_tx_self_insert on public.paper_vault_transactions
  for insert with check (auth.uid() = user_id);
-- service role inserts allowed via bypass

-- ---------------------------------------------------------------------
-- Auto-seed paper_accounts when a user finishes onboarding.
-- We hook into profiles update to capture their stock_capital_usd.
-- ---------------------------------------------------------------------
create or replace function public.seed_paper_account()
returns trigger language plpgsql security definer as $$
begin
  if new.onboarding_complete = true and (old.onboarding_complete is null or old.onboarding_complete = false) then
    insert into public.paper_accounts (user_id, starting_capital_usd, current_cash_usd)
    values (
      new.user_id,
      coalesce(new.stock_capital_usd, 0) + coalesce(new.options_capital_usd, 0),
      coalesce(new.stock_capital_usd, 0) + coalesce(new.options_capital_usd, 0)
    )
    on conflict (user_id) do nothing;
  end if;
  return new;
end;
$$;

drop trigger if exists on_profile_onboarded on public.profiles;
create trigger on_profile_onboarded
  after update on public.profiles
  for each row execute function public.seed_paper_account();

-- Backfill: seed for any user who already completed onboarding
insert into public.paper_accounts (user_id, starting_capital_usd, current_cash_usd)
select user_id,
       coalesce(stock_capital_usd, 0) + coalesce(options_capital_usd, 0),
       coalesce(stock_capital_usd, 0) + coalesce(options_capital_usd, 0)
from public.profiles
where onboarding_complete = true
on conflict (user_id) do nothing;
