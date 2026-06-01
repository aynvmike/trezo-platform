-- =====================================================================
-- Trezo — Phase 8c: safety kill-switches (TREZO_NOVA_BOT_TRADE_RULES §1)
--
-- Kill-switch state on paper_accounts. When a switch trips, the Risk
-- Manager vetoes every new signal:
--   - daily   : today's realized loss reaches 3% of day-start equity
--   - weekly  : this week's realized loss reaches 6% of week-start equity
--   - streak  : 3 losing trades in a row
--   - rejects : 3+ broker order rejects in a session (tracked in-process)
-- =====================================================================

alter table public.paper_accounts
  add column if not exists day_start_equity_usd numeric(14, 2);
alter table public.paper_accounts
  add column if not exists week_start_equity_usd numeric(14, 2);
alter table public.paper_accounts
  add column if not exists week_start_date date;
alter table public.paper_accounts
  add column if not exists week_realized_pnl_usd numeric(14, 2) not null default 0;
alter table public.paper_accounts
  add column if not exists consecutive_losses integer not null default 0;
alter table public.paper_accounts
  add column if not exists trading_halted boolean not null default false;
alter table public.paper_accounts
  add column if not exists halt_reason text;
alter table public.paper_accounts
  add column if not exists halt_scope text
  check (halt_scope is null or halt_scope in ('day', 'week', 'session'));
alter table public.paper_accounts
  add column if not exists halted_at timestamptz;
