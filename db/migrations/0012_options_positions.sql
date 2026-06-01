-- =====================================================================
-- Trezo — Phase 6d/6e: Options + Dividend Wheel positions
--
-- NOTE: premiums in this table are MODELED (Black-Scholes), not live
-- market quotes. Trezo has no options-chain feed yet.
-- =====================================================================

create table if not exists public.options_positions (
  id                uuid primary key default gen_random_uuid(),
  user_id           uuid not null references auth.users(id) on delete cascade,
  underlying        text not null,
  strategy          text not null,
    -- 'wheel_csp' | 'wheel_cc' | 'long_call' | 'bull_call_spread' | 'cash_secured_put'
  direction         text not null default 'income'
    check (direction in ('income', 'bullish', 'bearish', 'neutral')),
  -- Primary leg
  option_type       text check (option_type in ('call', 'put')),
  strike            numeric(20, 4),
  expiration        date,
  contracts         integer not null default 1 check (contracts > 0),
  -- Premium: positive = credit received (sold), negative = debit paid (bought)
  net_premium_usd   numeric(14, 4) not null default 0,
  modeled_iv        numeric(6, 4),
  -- Spreads / multi-leg detail
  legs              jsonb not null default '[]'::jsonb,
  -- Lifecycle
  status            text not null default 'open'
    check (status in ('open', 'closed_expired', 'closed_assigned', 'closed_manual', 'closed_profit')),
  realized_pnl_usd  numeric(14, 4),
  opened_at         timestamptz not null default now(),
  closed_at         timestamptz,
  notes             text,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

create index if not exists options_positions_user_idx
  on public.options_positions(user_id, status, opened_at desc);

drop trigger if exists options_positions_set_updated_at on public.options_positions;
create trigger options_positions_set_updated_at
  before update on public.options_positions
  for each row execute function public.set_updated_at();

alter table public.options_positions enable row level security;

drop policy if exists options_positions_self_all on public.options_positions;
create policy options_positions_self_all on public.options_positions
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
