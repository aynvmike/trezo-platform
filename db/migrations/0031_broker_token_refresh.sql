-- =====================================================================
-- Trezo — Phase 10c follow-up: OAuth token refresh audit + failure track
-- =====================================================================
-- Two pieces:
--   1) `broker_token_refresh_log` — append-only audit row per attempt.
--      Lets the user (and us) see when refreshes ran, whether they
--      worked, and what broke when they didn't.
--   2) `broker_connections.consecutive_refresh_failures` — when this
--      hits 3, the cron route flips status='expired' so the UI can
--      prompt the user to reconnect.
-- =====================================================================

alter table public.broker_connections
  add column if not exists consecutive_refresh_failures int not null default 0;

alter table public.broker_connections
  add column if not exists last_refresh_at timestamptz;

create table if not exists public.broker_token_refresh_log (
  id                       uuid primary key default gen_random_uuid(),
  broker_connection_id     uuid references public.broker_connections(id) on delete cascade,
  user_id                  uuid not null references auth.users(id) on delete cascade,
  broker                   text not null,
  status                   text not null check (status in ('refreshed', 'failed', 'skipped', 'no_refresher', 'malformed')),
  -- Free-text human-readable note. The cron route writes plain English
  -- here so the UI can show it without further interpretation.
  note                     text,
  -- New token's expiry timestamp on success; null on failure.
  new_expires_at           timestamptz,
  ran_at                   timestamptz not null default now()
);

create index if not exists broker_token_refresh_log_user_idx
  on public.broker_token_refresh_log(user_id, ran_at desc);

create index if not exists broker_token_refresh_log_conn_idx
  on public.broker_token_refresh_log(broker_connection_id, ran_at desc);

alter table public.broker_token_refresh_log enable row level security;

drop policy if exists broker_token_refresh_log_self_read on public.broker_token_refresh_log;
create policy broker_token_refresh_log_self_read on public.broker_token_refresh_log
  for select using (auth.uid() = user_id);

-- Service role inserts (the cron job runs with the service key, RLS bypassed).
comment on table public.broker_token_refresh_log is
  'Append-only audit of OAuth token refresh attempts. The user can SELECT their own rows; only service role writes.';

comment on column public.broker_connections.consecutive_refresh_failures is
  'Bumped on each failed refresh, reset to 0 on success. When >= 3 the cron job marks the row status=expired so the UI prompts a reconnect.';

comment on column public.broker_connections.last_refresh_at is
  'When the most recent refresh attempt ran (success or failure). Lets the UI show "last checked X minutes ago".';
