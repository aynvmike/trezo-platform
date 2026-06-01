-- =====================================================================
-- Trezo — Phase 13/14: outcome-aware learning loop
-- =====================================================================
-- `trade_outcomes` is a denormalized, append-only ledger of every
-- closed paper or live trade. One row per close. It pulls the entry
-- context (TCS, cycle, regime, pattern breakdown, filters that
-- matched) and pairs it with the realized outcome (exit reason, P&L,
-- hold time). The learning loop reads THIS table — not paper_positions
-- — so paper_positions can evolve without breaking analytics, and so
-- closed option legs can land in the same shape later.
--
-- The bot writes to this table on close. Mike views the rolled-up
-- stats on a Learning Insights panel. Auto-tuning bot_settings from
-- this data is OPT-IN and lives in a later phase.
-- =====================================================================

create table if not exists public.trade_outcomes (
  id                       uuid primary key default gen_random_uuid(),
  user_id                  uuid not null references auth.users(id) on delete cascade,

  -- Reference back to source (nullable - option closes come from a
  -- different table; backfilled data may not have an id).
  position_id              uuid,
  source_table             text check (source_table in ('paper_positions', 'options_positions') or source_table is null),

  -- What was traded
  ticker                   text not null,
  asset_type               text,                          -- stock/crypto/option
  side                     text,                          -- long/short
  strategy                 text,                          -- pattern, stms, orb, extended, crypto, wheel_csp, wheel_cc, ...
  direction                text,                          -- bullish/bearish/income

  -- Entry context — captured from the originating signal
  tcs_at_entry             int,
  iv_environment_at_entry  text,                          -- normal/high/earnings_day/post_earnings/dividend_window
  regime_at_entry          text,                          -- adaptive scope regime
  scope_paused_at_entry    text[],                        -- list of paused strategies at the time
  pattern_breakdown        jsonb,                         -- factor weights / scores
  entry_payload            jsonb,                         -- full signal payload for forensics

  -- Outcome
  exit_reason              text,                          -- stop/target/time/eod/manual/expired/assigned
  status                   text,                          -- closed_stop/closed_target/...
  entry_price              numeric(20, 8),
  exit_price               numeric(20, 8),
  quantity                 numeric(20, 8),
  realized_pnl_usd         numeric(14, 4),
  hold_minutes             int,

  -- Timeline
  opened_at                timestamptz,
  closed_at                timestamptz,
  created_at               timestamptz not null default now()
);

create index if not exists trade_outcomes_user_strat_idx
  on public.trade_outcomes(user_id, strategy, closed_at desc);

create index if not exists trade_outcomes_user_closed_idx
  on public.trade_outcomes(user_id, closed_at desc);

create index if not exists trade_outcomes_strategy_idx
  on public.trade_outcomes(strategy, closed_at desc);

alter table public.trade_outcomes enable row level security;

drop policy if exists trade_outcomes_self_read on public.trade_outcomes;
create policy trade_outcomes_self_read on public.trade_outcomes
  for select using (auth.uid() = user_id);

-- Service role inserts; UI never writes here (so RLS only covers SELECT).

comment on table public.trade_outcomes is
  'Append-only learning ledger - one row per closed trade with entry context + outcome. The learning loop reads this table directly.';
