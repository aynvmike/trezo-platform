-- 0051 -- let a PARTIAL close be written down.
--
-- WHY (2026-08-17 audit)
-- 0008 defined:
--   status text not null default 'open'
--     check (status in ('open','closed_stop','closed_target',
--                       'closed_manual','closed_time','closed_eod'))
-- On 2026-07-02 the profit-step ladder shipped, and it books a banked
-- slice by inserting a row with status 'closed_partial'. That value was
-- not in the list, so EVERY partial insert was rejected by the database.
-- The engine caught the exception, returned ok=False, and the log line
-- read "(booking failed)" with the reason discarded.
--
-- What that cost, for six weeks:
--   * the slice really sold at Alpaca -- the shares left the account
--   * the gain was never recorded, so realized P&L understated the book
--   * the open row's quantity was never reduced
--   * count_profit_steps() reads trade_outcomes for exit_reason
--     'profit_step'; nothing was ever written there, so the "restart-
--     proof" step counter never persisted and the ladder re-fired
--     step 1 over and over (GDX four times on 8/11, WMT across two days)
--   * by step 2 the OCO re-protect failed and the remainder sat naked
--
-- The list is widened here and, more importantly, code and schema now
-- share one source of truth: app/paper/position_status.py. A guard test
-- (agents/tests/test_position_status.py) fails if the code ever writes a
-- status this constraint would refuse -- so the next new status shows up
-- as a red test, not as six weeks of silently unbooked profit.

alter table public.paper_positions
  drop constraint if exists paper_positions_status_check;

alter table public.paper_positions
  add constraint paper_positions_status_check
  check (status in (
    'open',
    'closed_stop',
    'closed_target',
    'closed_manual',
    'closed_time',
    'closed_eod',
    -- 2026-08-17 additions
    'closed_partial',    -- a banked slice of a still-open position
    'closed_expired',    -- option expired worthless
    'closed_assigned',   -- option assigned / exercised
    'closed_adopted'     -- superseded by an adopted broker-truth row
  ));

comment on constraint paper_positions_status_check on public.paper_positions is
  'Keep in sync with app/paper/position_status.py. Adding a status in code '
  'without adding it here silently rejects every write that uses it -- see '
  'the 2026-07-02 to 2026-08-17 profit-step booking failure.';
