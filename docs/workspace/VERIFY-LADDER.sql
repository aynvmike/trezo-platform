-- =====================================================================
--  VERIFY THE PROFIT LADDER CAN ACTUALLY BANK  (Supabase SQL editor)
--  Read-only. Run top to bottom. Written 2026-08-17.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. Did migration 0051 actually take?
--    Expect a definition containing 'closed_partial'.
--    If it does NOT, nothing below matters -- every profit step still
--    sells at the broker and records nothing.
-- ---------------------------------------------------------------------
select conname,
       pg_get_constraintdef(oid) as definition,
       position('closed_partial' in pg_get_constraintdef(oid)) > 0
         as partial_allowed
from   pg_constraint
where  conname = 'paper_positions_status_check';


-- ---------------------------------------------------------------------
-- 2. Prove it end to end, without leaving anything behind.
--    Writes a row the OLD constraint would have rejected, then rolls
--    back. Expect: one row returned, then ROLLBACK. If it errors with
--    'violates check constraint', the migration did not apply.
--    Uses an existing book's user_id so foreign keys are satisfied.
-- ---------------------------------------------------------------------
begin;
insert into paper_positions
  (user_id, ticker, asset_type, side, quantity, entry_price,
   status, exit_price, exit_at, realized_pnl_usd)
select user_id, 'ZZTEST', 'stock', 'long', 1, 1.00,
       'closed_partial', 1.10, now(), 0.10
from   paper_accounts
limit  1
returning id, ticker, status;
rollback;


-- ---------------------------------------------------------------------
-- 3. Have any partials booked since the migration?
--    Before today this was ALWAYS zero -- that was the bug.
-- ---------------------------------------------------------------------
select date_trunc('day', exit_at) as day,
       count(*)                    as slices_booked,
       round(sum(realized_pnl_usd)::numeric, 2) as banked_usd
from   paper_positions
where  status = 'closed_partial'
group  by 1
order  by 1 desc
limit  10;


-- ---------------------------------------------------------------------
-- 4. The step counter's memory. count_profit_steps() reads THIS.
--    While booking failed, nothing was ever written here, so the
--    ladder forgot every step and re-fired step 1 (GDX 4x on 8/11).
-- ---------------------------------------------------------------------
select ticker,
       count(*) as steps_recorded,
       max(closed_at) as latest
from   trade_outcomes
where  exit_reason = 'profit_step'
group  by ticker
order  by latest desc nulls last
limit  20;


-- ---------------------------------------------------------------------
-- 5. Does the ledger know about the positions the broker holds?
--    This is the phantom-close damage. Until the CODE ships, expect
--    the two newer books to show far fewer open rows than Alpaca
--    holds (Alpaca showed 8 and 9 on 8/17; the ledger showed 1 each).
-- ---------------------------------------------------------------------
select a.user_id,
       count(p.id) filter (where p.status = 'open')            as open_rows,
       count(p.id) filter (where p.status = 'closed_manual'
                             and p.exit_at > now() - interval '7 days')
                                                               as manual_closes_7d
from   paper_accounts a
left   join paper_positions p on p.user_id = a.user_id
group  by a.user_id
order  by open_rows desc;


-- ---------------------------------------------------------------------
-- 6. Are the books still halted? (separate bug -- the kill-switch
--    freeze in the sentinel report; the migration does not touch it)
--    A row with trading_halted = true and consecutive_losses = 0 is
--    the stuck flag.
-- ---------------------------------------------------------------------
select user_id, trading_halted, halt_scope, halt_reason,
       consecutive_losses, today_realized_pnl_usd, halted_at
from   paper_accounts
order  by trading_halted desc;
