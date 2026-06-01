-- =====================================================================
-- Trezo — Phase 7.5: Adaptive Scope (Strategy Library + news/regime tuner)
--
-- Adds:
--   1. bot_settings.autonomy_mode — how much the Adaptive Scope engine
--      may do on its own: suggest | guarded | full.
--   2. strategy_scope_adjustments — the audit log of every scope change
--      the engine proposes or applies (regime postures + ticker flags).
--
-- Detected market events themselves are NOT given a table here — they
-- already persist as agent_messages rows (kind = 'event'), written by the
-- Market Sentiment and Research agents.
-- =====================================================================

-- 1. Autonomy mode on the existing bot_settings table -----------------
alter table public.bot_settings
  add column if not exists autonomy_mode text not null default 'guarded'
  check (autonomy_mode in ('suggest', 'guarded', 'full'));

-- 2. Scope-adjustment audit log ---------------------------------------
create table if not exists public.strategy_scope_adjustments (
  id                 uuid primary key default gen_random_uuid(),
  adjustment_id      text not null,            -- the engine's short id
  action             text not null,            -- 'set_posture' | 'flag_ticker'
  scope              text not null,            -- 'market' | a ticker symbol
  reason             text not null default '',
  trigger            text not null default '', -- 'regime:<r>' | 'event:<type>'
  severity           text not null default 'low'
    check (severity in ('low', 'medium', 'high')),
  status             text not null default 'applied'
    check (status in ('suggested', 'applied', 'expired', 'dismissed')),
  -- posture fields (neutral for flag_ticker rows)
  stop_multiplier    numeric(4, 2) not null default 1.00,
  tcs_bump           integer not null default 0,
  paused_strategies  jsonb not null default '[]'::jsonb,
  ttl_minutes        integer not null default 360,
  created_at         timestamptz not null default now()
);

create index if not exists scope_adjustments_created_idx
  on public.strategy_scope_adjustments(created_at desc);

create index if not exists scope_adjustments_status_idx
  on public.strategy_scope_adjustments(status, created_at desc);

alter table public.strategy_scope_adjustments enable row level security;

-- The adjustment log is bot-wide (not per-user). Any authenticated user
-- may read it; the agents service role inserts and bypasses RLS.
drop policy if exists scope_adjustments_read on public.strategy_scope_adjustments;
create policy scope_adjustments_read on public.strategy_scope_adjustments
  for select using (auth.uid() is not null);
