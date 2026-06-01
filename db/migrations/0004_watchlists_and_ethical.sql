-- =====================================================================
-- Trezo — Phase 3: Watchlists rework + Ethical filter system
-- =====================================================================

-- --------------------------------------------------------------------
-- ethical_exclusions — global table of tickers excluded per the spec.
-- Tier 1 = hard-block. Tier 2/3 = user-overridable (with logging).
-- Categories beyond defaults are mapped via `category` and gated by
-- the user's ethical_filter_settings.
-- --------------------------------------------------------------------
create table if not exists public.ethical_exclusions (
  id            uuid primary key default gen_random_uuid(),
  ticker        text not null,
  category      text not null,   -- e.g. 'human_rights', 'tobacco', 'weapons', 'fossil_fuels', 'private_prisons', etc.
  tier          integer not null check (tier in (1, 2, 3, 4)),
                                 -- 1-3 = default exclusions (always on), 4 = user-toggleable
  source        text not null,   -- 'SAM.gov', 'OFAC', 'SEC', 'static-list', etc.
  source_url    text,
  source_date   date,
  evidence      text,            -- one-line summary of why
  active        boolean not null default true,
  created_at    timestamptz not null default now(),
  unique (ticker, category)
);

create index if not exists ethical_exclusions_ticker_idx on public.ethical_exclusions(ticker) where active;
create index if not exists ethical_exclusions_category_idx on public.ethical_exclusions(category) where active;

-- ethical_exclusions is global (no user_id). Anyone authenticated can read.
alter table public.ethical_exclusions enable row level security;

drop policy if exists ethical_exclusions_read on public.ethical_exclusions;
create policy ethical_exclusions_read on public.ethical_exclusions
  for select using (auth.role() = 'authenticated');
-- inserts/updates only from service role (admin sync job)

-- --------------------------------------------------------------------
-- ethical_filter_settings — per-user opt-in categories beyond defaults
-- --------------------------------------------------------------------
create table if not exists public.ethical_filter_settings (
  user_id              uuid primary key references auth.users(id) on delete cascade,
  exclude_tobacco      boolean not null default false,
  exclude_weapons      boolean not null default false,
  exclude_fossil_fuels boolean not null default false,
  exclude_private_prisons boolean not null default false,
  exclude_gambling     boolean not null default false,
  exclude_predatory_lending boolean not null default false,
  exclude_animal_testing boolean not null default false,
  exclude_adult_entertainment boolean not null default false,
  exclude_cannabis     boolean not null default false,
  exclude_crypto_mining boolean not null default false,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now()
);

drop trigger if exists ethical_filter_settings_set_updated_at on public.ethical_filter_settings;
create trigger ethical_filter_settings_set_updated_at
  before update on public.ethical_filter_settings
  for each row execute function public.set_updated_at();

alter table public.ethical_filter_settings enable row level security;

drop policy if exists ethical_filter_settings_self_all on public.ethical_filter_settings;
create policy ethical_filter_settings_self_all on public.ethical_filter_settings
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- --------------------------------------------------------------------
-- ethical_overrides — audit log of user overrides on excluded tickers
-- --------------------------------------------------------------------
create table if not exists public.ethical_overrides (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references auth.users(id) on delete cascade,
  ticker       text not null,
  category     text not null,
  tier         integer not null,
  reason       text not null,
  created_at   timestamptz not null default now()
);

create index if not exists ethical_overrides_user_idx on public.ethical_overrides(user_id, created_at desc);

alter table public.ethical_overrides enable row level security;

drop policy if exists ethical_overrides_self_select on public.ethical_overrides;
create policy ethical_overrides_self_select on public.ethical_overrides
  for select using (auth.uid() = user_id);

drop policy if exists ethical_overrides_self_insert on public.ethical_overrides;
create policy ethical_overrides_self_insert on public.ethical_overrides
  for insert with check (auth.uid() = user_id);

-- --------------------------------------------------------------------
-- watchlist_items — extend with override flag (so we can mark overridden
-- tickers in the UI)
-- --------------------------------------------------------------------
alter table public.watchlist_items
  add column if not exists ethical_override boolean not null default false,
  add column if not exists ethical_override_reason text;
