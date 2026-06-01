-- 0030 — Expert mode overrides.
--
-- Mike Phase 13a follow-up (2026-05-30). Today's Expert preset just
-- unlocks raw R:R sliders. This migration broadens it: per-stock
-- pins that override the Strategy Engine's pick, and per-stock
-- disables that block Risk Manager from approving any signal on the
-- name.
--
-- Both override types have a TTL so a "skip NVDA today" override
-- doesn't linger forever - the agent prunes expired rows on every
-- tick. NULL `expires_at` means "until explicitly removed."

alter table bot_settings
  add column if not exists expert_mode_enabled boolean not null default false;

comment on column bot_settings.expert_mode_enabled is
  'When true, the Bot Tuning UI surfaces the Expert Overrides section (per-stock strategy pin + disable list). Underlying overrides apply whether this is on or off; the toggle just gates the UI.';


create table if not exists stock_strategy_overrides (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  ticker text not null,
  strategy text not null,
  reason text,
  expires_at timestamptz,
  created_at timestamptz not null default now(),
  unique (user_id, ticker)
);

comment on table stock_strategy_overrides is
  'Per-(user, ticker) strategy pin. When present, select_strategy() returns this strategy instead of running its scorer pool. Use sparingly; the per-stock selector is usually smarter than a manual pin.';

create index if not exists stock_strategy_overrides_user_idx
  on stock_strategy_overrides (user_id, ticker);


create table if not exists stock_disabled (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  ticker text not null,
  reason text,
  expires_at timestamptz,
  created_at timestamptz not null default now(),
  unique (user_id, ticker)
);

comment on table stock_disabled is
  'Per-(user, ticker) "do not trade" list. Risk Manager vetoes every signal on a ticker that appears here, with the user-supplied reason in the veto note.';

create index if not exists stock_disabled_user_idx
  on stock_disabled (user_id, ticker);


-- Row-level security: each user can read / write only their own rows.
alter table stock_strategy_overrides enable row level security;
alter table stock_disabled enable row level security;

drop policy if exists "user manages own strategy overrides" on stock_strategy_overrides;
create policy "user manages own strategy overrides"
  on stock_strategy_overrides
  for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

drop policy if exists "user manages own disabled list" on stock_disabled;
create policy "user manages own disabled list"
  on stock_disabled
  for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);
