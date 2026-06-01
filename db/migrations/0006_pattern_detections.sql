-- =====================================================================
-- Trezo — Phase 4: Pattern Detection
-- =====================================================================

create table if not exists public.pattern_detections (
  id                  uuid primary key default gen_random_uuid(),
  user_id             uuid references auth.users(id) on delete cascade,
  ticker              text not null,
  asset_type          text not null,
  dominant_pattern    text,
  detected_patterns   text[] not null default '{}',
  direction           text check (direction in ('bullish', 'bearish', 'neutral')),
  score               integer not null check (score between 0 and 100),
  tcs                 integer not null check (tcs between 0 and 1000),
  breakdown           jsonb not null default '{}'::jsonb,
  confluence          jsonb not null default '{}'::jsonb,
  detected_at         timestamptz not null default now()
);

create index if not exists pattern_detections_user_idx on public.pattern_detections(user_id, detected_at desc);
create index if not exists pattern_detections_ticker_idx on public.pattern_detections(ticker, detected_at desc);

alter table public.pattern_detections enable row level security;

drop policy if exists pattern_detections_self_all on public.pattern_detections;
create policy pattern_detections_self_all on public.pattern_detections
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- ---------------------------------------------------------------------
-- pattern_accuracy — feedback loop for the Strategy Discovery Agent.
-- Updated by a background job (Phase 5+). Public read for auth users.
-- ---------------------------------------------------------------------
create table if not exists public.pattern_accuracy (
  pattern         text not null,
  timeframe       text not null,
  total_detections integer not null default 0,
  wins            integer not null default 0,
  losses          integer not null default 0,
  win_rate        numeric(5, 2) not null default 0.0,
  average_pnl     numeric(14, 2) not null default 0.0,
  updated_at      timestamptz not null default now(),
  primary key (pattern, timeframe)
);

alter table public.pattern_accuracy enable row level security;

drop policy if exists pattern_accuracy_read on public.pattern_accuracy;
create policy pattern_accuracy_read on public.pattern_accuracy
  for select using (auth.role() = 'authenticated');
