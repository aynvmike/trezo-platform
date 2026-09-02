-- 0060: three authorization gaps from the 2026-09-01 audit
--                                     (findings AUTH-03, AUTH-04, AUTH-05)
--
-- 1. AUTH-03  ops_health_alerts was readable by ANYONE holding the anon
--    key: 0040 created its SELECT policy as USING (true) with a comment
--    saying "authenticated users read all rows" -- the comment described
--    the intent, the predicate did not enforce it. The table has no
--    user_id (platform-level monitoring), so owner scoping has no clean
--    predicate; the policy now requires the authenticated role, wrapped
--    in (select ...) per the 0042 initplan convention.
--
-- 2. AUTH-04  public.ops_heartbeat_check() is SECURITY DEFINER (0052,
--    rewritten 0054/0055) and was never locked down the way 0041 locked
--    the other definer functions: any anon/authenticated caller could
--    hit /rest/v1/rpc/ops_heartbeat_check and drive the Discord webhook
--    (spam it, or exhaust the 30-minute quiet latch so a real alarm is
--    swallowed). pg_cron runs the job as the function owner, which is
--    unaffected by revoking from the API roles -- same shape as 0041.
--
-- 3. AUTH-05  trading_accounts.owner_id has no foreign key. 0045 created
--    the column bare and 0047 made it the root of the person -> accounts
--    -> books chain, but nothing stops a row from naming an owner that
--    does not exist in auth.users, and deleting a person leaves their
--    accounts (and, via 0047's CASCADE, all their books) orphaned but
--    alive. 0047's seed step also registered "books owned by themselves"
--    for any user_id it found in a book table -- a stray id there would
--    have become a trading_accounts row whose owner_id matches no user.
--    So this is added SAFELY: a diagnostic first, then NOT VALID (so the
--    constraint definition lands without scanning), then VALIDATE (which
--    scans and FAILS LOUDLY on a mismatch, rolling the whole file back).
--    ON DELETE RESTRICT, not CASCADE (review 2026-09-01, :108): with
--    0047's CASCADE from trading_accounts to every book table, a CASCADE
--    here would let ONE click in the Supabase Auth dashboard (delete the
--    owner) hard-delete all three paper books' positions, trades and
--    outcomes in a single statement. RESTRICT gives the same integrity
--    guarantee (no orphan can be created) and turns that click into a
--    refusal: delete the accounts deliberately first, then the person.
--    Idempotent: a database that already carries the CASCADE form of
--    this constraint from an earlier draft is re-pointed to RESTRICT.
--
-- Apply by hand in the Supabase SQL editor (whole file at once).

-- ---------------------------------------------------------------------
-- RUN FIRST (AUTH-05 diagnostic) -- read-only. Every row it returns is a
-- trading_accounts row whose owner_id matches no auth.users id. If it
-- returns ANY rows, stop: decide per row (repoint owner_id to the real
-- person, or delete the stray account) BEFORE applying the rest. The
-- migration below re-checks and refuses on its own, but this shows you
-- the rows rather than just the count.
--
--   select ta.account_key, ta.owner_id, ta.label, ta.broker, ta.is_paper,
--          ta.created_at
--   from public.trading_accounts ta
--   left join auth.users u on u.id = ta.owner_id
--   where u.id is null
--   order by ta.created_at;
-- ---------------------------------------------------------------------

begin;

-- ---- 1) AUTH-03: ops_health_alerts readable by authenticated only ---
drop policy if exists "ops_health_alerts read all" on public.ops_health_alerts;
drop policy if exists "ops_health_alerts read authenticated" on public.ops_health_alerts;
create policy "ops_health_alerts read authenticated"
  on public.ops_health_alerts
  for select
  using ((select auth.role()) = 'authenticated');
-- Service role bypasses RLS, so the watchdog's inserts are unaffected.

-- ---- 2) AUTH-04: lock down the heartbeat definer function ------------
-- Mirrors 0041: revoke external EXECUTE, pin search_path. Signature is
-- ops_heartbeat_check() returning void (0052/0054/0055). Guarded so the
-- file still applies on a database where 0052 was never run.
do $auth04$
begin
  if exists (select 1 from pg_proc p
             join pg_namespace n on n.oid = p.pronamespace
             where n.nspname = 'public' and p.proname = 'ops_heartbeat_check') then
    revoke execute on function public.ops_heartbeat_check() from anon, authenticated, public;
    alter function public.ops_heartbeat_check() set search_path = pg_catalog, public;
    raise notice 'AUTH-04: ops_heartbeat_check() EXECUTE revoked from anon/authenticated/public';
  else
    raise notice 'AUTH-04: ops_heartbeat_check() not present, skipped';
  end if;
end
$auth04$;

-- ---- 3) AUTH-05: trading_accounts.owner_id -> auth.users(id) --------
-- Refuse, with the offending ids in the message, before touching the
-- constraint. VALIDATE below would also refuse, but with less to go on.
do $auth05_check$
declare
  n    bigint;
  ids  text;
begin
  select count(*), string_agg(ta.account_key::text || ' (owner ' || ta.owner_id::text || ')', ', ')
    into n, ids
  from public.trading_accounts ta
  left join auth.users u on u.id = ta.owner_id
  where u.id is null;

  if n > 0 then
    raise exception 'AUTH-05: % trading_accounts row(s) have an owner_id with no auth.users match: %. '
                    'Fix those rows first (see the RUN FIRST query at the top of 0060).', n, ids;
  end if;
  raise notice 'AUTH-05: every trading_accounts.owner_id matches an auth.users row';
end
$auth05_check$;

do $auth05_add$
begin
  if not exists (select 1 from pg_constraint
                 where conname = 'trading_accounts_owner_id_fkey'
                   and conrelid = 'public.trading_accounts'::regclass) then
    alter table public.trading_accounts
      add constraint trading_accounts_owner_id_fkey
      foreign key (owner_id) references auth.users(id) on delete restrict
      not valid;
    raise notice 'AUTH-05: trading_accounts_owner_id_fkey added NOT VALID (ON DELETE RESTRICT)';
  elsif exists (select 1 from pg_constraint
                where conname = 'trading_accounts_owner_id_fkey'
                  and conrelid = 'public.trading_accounts'::regclass
                  and confdeltype = 'c') then
    -- Earlier draft of this file used CASCADE (review 2026-09-01, :108):
    -- re-point it so deleting the owner is refused, not fanned out into
    -- every book table.
    alter table public.trading_accounts
      drop constraint trading_accounts_owner_id_fkey;
    alter table public.trading_accounts
      add constraint trading_accounts_owner_id_fkey
      foreign key (owner_id) references auth.users(id) on delete restrict
      not valid;
    raise notice 'AUTH-05: trading_accounts_owner_id_fkey re-created as ON DELETE RESTRICT (was CASCADE)';
  else
    raise notice 'AUTH-05: trading_accounts_owner_id_fkey already present (ON DELETE RESTRICT)';
  end if;
end
$auth05_add$;

-- Scans every row; a mismatch raises and rolls the whole file back.
alter table public.trading_accounts validate constraint trading_accounts_owner_id_fkey;

comment on constraint trading_accounts_owner_id_fkey on public.trading_accounts is
  'AUTH-05 (0060): the person at the root of the person -> accounts -> '
  'books chain must exist. ON DELETE RESTRICT: deleting the person is '
  'refused while accounts (and, via 0047, books) still hang off them -- '
  'remove the accounts deliberately first. No orphan, no one-click wipe.';

-- Ledger (0058 convention).
insert into public.schema_migrations (version, assumed, notes) values
  ('0060_security_authz', false,
   'AUTH-03 ops_health_alerts authenticated-only; AUTH-04 ops_heartbeat_check EXECUTE revoked; '
   'AUTH-05 trading_accounts.owner_id FK -> auth.users')
on conflict (version) do nothing;

commit;

-- Confirmation.
select 'ops_health_alerts select policies' as check,
       string_agg(policyname || ': ' || qual, '; ') as detail
from pg_policies
where schemaname = 'public' and tablename = 'ops_health_alerts' and cmd = 'SELECT'
union all
select 'ops_heartbeat_check executable by anon/authenticated',
       (has_function_privilege('anon', 'public.ops_heartbeat_check()', 'EXECUTE')
        or has_function_privilege('authenticated', 'public.ops_heartbeat_check()', 'EXECUTE'))::text
union all
select 'trading_accounts_owner_id_fkey validated',
       convalidated::text
from pg_constraint
where conname = 'trading_accounts_owner_id_fkey';
