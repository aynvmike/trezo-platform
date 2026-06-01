-- ============================================================================
-- Migration 0027: Risk profile + per-user reward:risk floor
-- ============================================================================
-- Adds two columns to bot_settings:
--   risk_profile     — 'conservative' | 'balanced' | 'aggressive' | 'expert'
--                      drives the high-level preset for stop/target/risk/RR
--   min_reward_risk  — the reward:risk floor enforced by sizing.py
--                      conservative=2.0, balanced=1.5, aggressive=0.5, expert=user-set
--                      Clamped 0.3..3.0 in code so it can never disable the floor.
--
-- Also creates risk_profile_audit table so toggling Expert mode (or any
-- raw R:R change) writes an audit row — the user can't blame the agent
-- for a setting they made themselves.
-- ============================================================================

alter table public.bot_settings
  add column if not exists risk_profile text not null default 'balanced'
    check (risk_profile in ('conservative', 'balanced', 'aggressive', 'expert')),
  add column if not exists min_reward_risk numeric(6,2) not null default 1.5
    check (min_reward_risk >= 0.3 and min_reward_risk <= 3.0);

create table if not exists public.risk_profile_audit (
  id              uuid primary key default gen_random_uuid(),
  user_id         uuid not null references auth.users(id) on delete cascade,
  changed_at      timestamptz not null default now(),
  from_profile    text,
  to_profile      text not null,
  from_rr         numeric(6,2),
  to_rr           numeric(6,2),
  from_stop_pct   numeric(6,4),
  to_stop_pct     numeric(6,4),
  from_target_pct numeric(6,4),
  to_target_pct   numeric(6,4),
  from_risk_pct   numeric(6,4),
  to_risk_pct     numeric(6,4),
  note            text
);

create index if not exists risk_profile_audit_user_idx
  on public.risk_profile_audit(user_id, changed_at desc);

alter table public.risk_profile_audit enable row level security;

drop policy if exists risk_profile_audit_self_read on public.risk_profile_audit;
create policy risk_profile_audit_self_read on public.risk_profile_audit
  for select using (auth.uid() = user_id);

drop policy if exists risk_profile_audit_self_write on public.risk_profile_audit;
create policy risk_profile_audit_self_write on public.risk_profile_audit
  for insert with check (auth.uid() = user_id);
