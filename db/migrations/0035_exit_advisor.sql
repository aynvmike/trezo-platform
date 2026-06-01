-- =====================================================================
-- Trezo — Phase 13d: real-time held-too-long advisor
-- =====================================================================
-- Two tiny pieces of state, designed to be cheap to write every 5 min:
--
-- 1. Per-position running MFE tracker. We store peak_unrealized_pnl_usd
--    and the timestamp of that peak directly on paper_positions so the
--    advisor agent can answer "how far off peak are we?" without
--    re-scanning history. Updated every tick when the open position
--    prints a new high-water mark.
--
-- 2. exit_advisor_alerts append-only log. One row per alert raised, so
--    the dashboard can show the live alert AND so Mike can audit the
--    bot's reasoning later. RLS lets the user read their own rows.
--
-- The advisor never closes a position. It surfaces alerts; Mike acts.
-- =====================================================================

alter table public.paper_positions
  add column if not exists peak_unrealized_pnl_usd numeric(14, 4);
alter table public.paper_positions
  add column if not exists peak_price numeric(20, 8);
alter table public.paper_positions
  add column if not exists peak_at timestamptz;

create table if not exists public.exit_advisor_alerts (
  id                       uuid primary key default gen_random_uuid(),
  user_id                  uuid not null references auth.users(id) on delete cascade,
  position_id              uuid references public.paper_positions(id) on delete cascade,
  ticker                   text not null,
  -- One of: 'held_too_long', 'peak_giveback', 'trend_break',
  -- 'target_hit', 'stop_approaching', 'time_in_trade'.
  alert_kind               text not null,
  severity                 text not null default 'info' check (severity in ('info', 'warn', 'urgent')),
  -- Plain-English explanation the UI shows verbatim.
  message                  text not null,
  -- Snapshot of the numbers behind the alert so we can audit later.
  current_price            numeric(20, 8),
  peak_price               numeric(20, 8),
  giveback_pct             numeric(8, 4),
  unrealized_pnl_usd       numeric(14, 4),
  raised_at                timestamptz not null default now(),
  -- Set when the user dismisses/snoozes the alert so we don't pop the
  -- same suggestion every tick.
  acknowledged_at          timestamptz
);

create index if not exists exit_advisor_alerts_user_idx
  on public.exit_advisor_alerts(user_id, raised_at desc);

create index if not exists exit_advisor_alerts_open_idx
  on public.exit_advisor_alerts(user_id, position_id)
  where acknowledged_at is null;

alter table public.exit_advisor_alerts enable row level security;

drop policy if exists exit_advisor_alerts_self_all on public.exit_advisor_alerts;
create policy exit_advisor_alerts_self_all on public.exit_advisor_alerts
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

comment on table public.exit_advisor_alerts is
  'Real-time advisor alerts. The bot does not close trades; it surfaces "consider trimming" suggestions for Mike to act on.';
comment on column public.paper_positions.peak_unrealized_pnl_usd is
  'Running high-water mark of the position''s unrealized P&L. Updated by ExitAdvisorAgent every tick. Used to detect held-too-long peak-giveback patterns.';
