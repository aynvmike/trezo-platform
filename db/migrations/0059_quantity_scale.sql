-- 0059: quantity columns widen from numeric(20,8) to numeric(30,12)
--                                       (2026-09-01 audit, finding QP-01)
--
-- WHY
-- paper_positions.quantity, trades.quantity and trade_outcomes.quantity
-- were all declared numeric(20, 8) (0008, 0001, 0032). Alpaca reports
-- crypto quantities at NINE decimals. Postgres rounds on the way in, so
-- the ledger and the venue disagreed by up to 5e-9 of a coin on every
-- crypto fill:
--   * rounded UP  -> the resting-stop placement asked to sell 3e-9 more
--     DOT than the account held; every placement 403'd "insufficient
--     balance", and $10.9k of coin sat with no floor for days (the
--     2026-08-28 DOT loop).
--   * rounded DOWN -> the other books were left holding dust crumbs the
--     ledger did not know about.
-- Scale 12 holds anything Alpaca (9 dp) or a crypto exchange (typically
-- 8-10 dp) can report, with room to spare; precision 30 keeps the
-- integer part generous. The CHECK constraints (quantity > 0) are
-- untouched by ALTER COLUMN TYPE and remain in force.
--
-- DEFENCE IN DEPTH: app/brokers/alpaca.py (ratchet_crypto_stop and the
-- QTY PRECISION note in it) still asks the venue what it actually holds
-- and clamps the stop quantity to that figure. That clamp STAYS. This
-- migration removes the reason the clamp was ever needed; the clamp
-- remains for the day a venue reports more decimals than we store.
--
-- Postgres rewrites a table when a numeric column's SCALE changes, so
-- each ALTER takes an exclusive lock for the duration; the three tables
-- are small (thousands of rows) and this runs in well under a second.
-- Idempotent: the DO block only alters columns not already at scale 12.
--
-- Apply by hand in the Supabase SQL editor (whole file at once).

begin;

do $qp$
declare
  t   text;
  sc  int;
begin
  foreach t in array array['paper_positions', 'trades', 'trade_outcomes'] loop
    if to_regclass('public.' || t) is null then
      raise notice 'QP-01: table public.% not present, skipped', t;
      continue;
    end if;

    select numeric_scale into sc
    from information_schema.columns
    where table_schema = 'public' and table_name = t and column_name = 'quantity';

    if sc is null then
      raise notice 'QP-01: public.%.quantity not found, skipped', t;
    elsif sc >= 12 then
      raise notice 'QP-01: public.%.quantity already at scale %, skipped', t, sc;
    else
      execute format('alter table public.%I alter column quantity type numeric(30, 12)', t);
      -- rv:data-lane: report the scale that was actually there (the
      -- branch fires for ANY scale < 12, not only the original 8).
      raise notice 'QP-01: public.%.quantity widened from scale % -> numeric(30,12)', t, sc;
    end if;
  end loop;
end
$qp$;

comment on column public.paper_positions.quantity is
  'numeric(30,12) since 0059 (QP-01): Alpaca reports crypto at 9 dp; the '
  'old 8-dp scale rounded fills and manufactured stop-placement 403s.';

-- Ledger (0058 convention).
insert into public.schema_migrations (version, assumed, notes) values
  ('0059_quantity_scale', false,
   'QP-01: quantity numeric(20,8) -> numeric(30,12) on paper_positions, trades, trade_outcomes')
on conflict (version) do nothing;

commit;

-- Confirmation: all three should read scale 12.
select table_name, numeric_precision, numeric_scale
from information_schema.columns
where table_schema = 'public'
  and column_name = 'quantity'
  and table_name in ('paper_positions', 'trades', 'trade_outcomes')
order by table_name;
