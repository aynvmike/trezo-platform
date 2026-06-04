-- 0039 - Per-user options Greek filters + hopeful cap
-- Promotes the env-only Phase C+D settings into per-user bot_settings
-- so Mike can tune them from Bot Tuning (Expert mode) without editing
-- agents/.env.
--
-- Defaults mirror the agents/.env defaults from Phase C+D.

alter table bot_settings
  add column if not exists options_min_dte integer not null default 7,
  add column if not exists options_max_premium_delta numeric(6, 4) not null default 0.45,
  add column if not exists options_min_iv_rank_scalp numeric(6, 2) not null default 30.0,
  add column if not exists options_hopeful_allocation_cap_pct numeric(6, 4) not null default 0.03;

-- Lightweight value bounds. Values outside these would be silently
-- broken by the agent anyway, so reject at write time.
do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'bot_settings_options_min_dte_range'
  ) then
    alter table bot_settings
      add constraint bot_settings_options_min_dte_range
        check (options_min_dte between 0 and 90);
  end if;
  if not exists (
    select 1 from pg_constraint where conname = 'bot_settings_options_max_premium_delta_range'
  ) then
    alter table bot_settings
      add constraint bot_settings_options_max_premium_delta_range
        check (options_max_premium_delta between 0 and 1);
  end if;
  if not exists (
    select 1 from pg_constraint where conname = 'bot_settings_options_min_iv_rank_scalp_range'
  ) then
    alter table bot_settings
      add constraint bot_settings_options_min_iv_rank_scalp_range
        check (options_min_iv_rank_scalp between 0 and 100);
  end if;
  if not exists (
    select 1 from pg_constraint where conname = 'bot_settings_options_hopeful_cap_range'
  ) then
    alter table bot_settings
      add constraint bot_settings_options_hopeful_cap_range
        check (options_hopeful_allocation_cap_pct between 0 and 1);
  end if;
end $$;
