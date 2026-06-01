-- =====================================================================
-- Trezo — Phase 8b: broker routing on paper_positions
--
-- Stock trades now route through Alpaca's paper-trading API. A position
-- row records which venue executed it, and the broker's order id, so the
-- Position Monitor can skip Alpaca-managed positions (Alpaca's bracket
-- order manages the stop/target server-side).
-- =====================================================================

alter table public.paper_positions
  add column if not exists broker text not null default 'paper'
  check (broker in ('paper', 'alpaca'));

alter table public.paper_positions
  add column if not exists broker_order_id text;

create index if not exists paper_positions_broker_idx
  on public.paper_positions(broker, status);
