-- 0023_backtest_runs.sql
-- Phase 12d — persist every backtest run so a strategy's history is
-- kept, and so the agents can later learn from past results (Phase 13).

create table if not exists public.backtest_runs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  symbol text not null,
  strategy text not null,
  tcs_threshold int not null default 700,
  stop_pct numeric not null default 0.05,
  target_pct numeric not null default 0.10,
  period text not null default '2y',
  bars int not null default 0,
  trades int not null default 0,
  win_rate numeric not null default 0,
  profit_factor numeric not null default 0,
  expectancy_pct numeric not null default 0,
  total_return_pct numeric not null default 0,
  max_drawdown_pct numeric not null default 0,
  created_at timestamptz not null default now()
);

create index if not exists backtest_runs_user_idx
  on public.backtest_runs (user_id, created_at desc);

alter table public.backtest_runs enable row level security;

-- A user owns their own runs. The agents service (service-role key)
-- bypasses RLS, so it can read every run when learning from history.
create policy "backtest_runs_select_own" on public.backtest_runs
  for select using (auth.uid() = user_id);
create policy "backtest_runs_insert_own" on public.backtest_runs
  for insert with check (auth.uid() = user_id);
create policy "backtest_runs_delete_own" on public.backtest_runs
  for delete using (auth.uid() = user_id);

comment on table public.backtest_runs is
  'History of strategy backtests — feeds the agents'' learning loop.';
