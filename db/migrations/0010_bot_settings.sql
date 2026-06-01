-- =====================================================================
-- Trezo — Phase 6c: Bot tuning settings
-- =====================================================================

create table if not exists public.bot_settings (
  user_id               uuid primary key references auth.users(id) on delete cascade,
  -- Risk Manager
  tcs_threshold         integer not null default 700 check (tcs_threshold between 300 and 1000),
  max_open_positions    integer not null default 3   check (max_open_positions between 1 and 20),
  -- Position sizing (paper engine)
  risk_per_trade_pct    numeric(5, 4) not null default 0.05 check (risk_per_trade_pct between 0.005 and 0.25),
  default_stop_pct      numeric(5, 4) not null default 0.05 check (default_stop_pct between 0.01 and 0.50),
  default_target_pct    numeric(5, 4) not null default 0.10 check (default_target_pct between 0.01 and 1.00),
  -- Per-strategy enable toggles
  pattern_enabled       boolean not null default true,
  stms_enabled          boolean not null default true,
  crypto_enabled        boolean not null default true,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now()
);

drop trigger if exists bot_settings_set_updated_at on public.bot_settings;
create trigger bot_settings_set_updated_at
  before update on public.bot_settings
  for each row execute function public.set_updated_at();

alter table public.bot_settings enable row level security;

drop policy if exists bot_settings_self_all on public.bot_settings;
create policy bot_settings_self_all on public.bot_settings
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- Allow the agents service (service role) to read everyone's settings.
drop policy if exists bot_settings_service_read on public.bot_settings;
-- (service role bypasses RLS automatically; no extra policy needed)

-- Seed a default row for every already-onboarded user
insert into public.bot_settings (user_id)
select user_id from public.profiles where onboarding_complete = true
on conflict (user_id) do nothing;

-- Auto-seed on future onboarding completion
create or replace function public.seed_bot_settings()
returns trigger language plpgsql security definer as $$
begin
  if new.onboarding_complete = true and (old.onboarding_complete is null or old.onboarding_complete = false) then
    insert into public.bot_settings (user_id) values (new.user_id)
    on conflict (user_id) do nothing;
  end if;
  return new;
end;
$$;

drop trigger if exists on_profile_onboarded_bot_settings on public.profiles;
create trigger on_profile_onboarded_bot_settings
  after update on public.profiles
  for each row execute function public.seed_bot_settings();
