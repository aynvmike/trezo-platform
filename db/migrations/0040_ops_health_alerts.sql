-- 0040 - Operations Watchdog alerts table.
-- New 21st agent (ops_watchdog) writes here when an agent is missing
-- from the registry or has gone silent during market hours. Mike's
-- 2026-06-03 ask: never let the bot go silent for 4 days again.

create table if not exists public.ops_health_alerts (
  id           uuid primary key default gen_random_uuid(),
  alert_kind   text not null,
    -- 'missing_agent' | 'stuck_agent' | 'recovered' | 'bootstrap_fail'
  target_name  text not null,
  severity     text not null check (severity in ('info', 'warn', 'urgent')),
  message      text not null,
  raised_at    timestamptz not null default now(),
  acknowledged_at timestamptz
);

create index if not exists ops_health_alerts_open_idx
  on public.ops_health_alerts (raised_at desc)
  where acknowledged_at is null;

-- Platform-level monitoring; not per-user, so no RLS user_id.
-- Service role inserts; authenticated users read all rows. Adjust if
-- multi-tenant deployment ever lands.
alter table public.ops_health_alerts enable row level security;

-- Postgres does NOT support `CREATE POLICY IF NOT EXISTS`. The
-- idempotent pattern is drop-then-create so the migration can be
-- safely re-run.
drop policy if exists "ops_health_alerts read all" on public.ops_health_alerts;
create policy "ops_health_alerts read all"
  on public.ops_health_alerts
  for select
  using (true);
