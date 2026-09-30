// PGlite 0.5.8: actual trigger/RPC/role tests, not a Python imitation of SQL.
import { readFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
const { PGlite } = await import(process.env.PGLITE_MODULE || '@electric-sql/pglite');
const db = new PGlite();
const A = '00000000-0000-0000-0000-000000000001';
const B = '00000000-0000-0000-0000-000000000002';
try {
  await db.exec(`
    create role anon; create role authenticated; create role service_role bypassrls;
    create table trading_accounts(account_key uuid primary key);
    insert into trading_accounts values('${A}'),('${B}');
    create table bot_settings(user_id uuid primary key);
    create table paper_accounts(user_id uuid primary key, today_realized_pnl_usd numeric,
      last_reset_date date);
    insert into paper_accounts values('${A}',0,current_date),('${B}',0,current_date);
    insert into bot_settings values('${A}'),('${B}');
    create function my_account_keys() returns setof uuid language sql as
      $$ select '${A}'::uuid $$;
    grant usage on schema public to service_role,authenticated;
    grant select,update on paper_accounts to service_role;
    grant select on trading_accounts to service_role;
    grant select,update on paper_accounts to authenticated;
    alter table paper_accounts enable row level security;
    create policy own_accounts on paper_accounts to authenticated
      using(user_id in (select my_account_keys())) with check(user_id in (select my_account_keys()));
  `);
  const migration = await readFile(new URL('../../supabase/migrations/20260921152142_day_trade_income.sql', import.meta.url), 'utf8');
  await db.exec(migration);
  const query = async sql => (await db.query(sql)).rows;
  assert.equal((await query(`select bool_and(goal_lock_enabled) as on from bot_settings`))[0].on, true);
  await db.exec('set role service_role');
  const observe = async (uid, announce=true) => (await query(`select observe_daily_goal('${uid}',50,'grind',${announce}) as result`))[0].result;
  assert.equal((await observe(A)).locked, false);
  assert.equal((await observe(B)).locked, false);
  await db.exec(`update paper_accounts set today_realized_pnl_usd=60 where user_id='${A}'`);
  // Giveback happens BEFORE another entry. Trigger must already have latched.
  await db.exec(`update paper_accounts set today_realized_pnl_usd=10 where user_id='${A}'`);
  const lock = await observe(A);
  assert.equal(lock.locked, true);
  assert.equal(lock.realized_at_lock, 60);
  assert.equal(lock.first_refusal, true);
  assert.equal((await observe(A)).first_refusal, false);
  assert.equal((await observe(B)).locked, false);
  // New process has no Python memory; persistent RPC remains locked.
  assert.equal((await observe(A)).locked, true);
  // Simulate yesterday's persisted state and an account rollover.
  await db.exec(`update book_goal_locks set day=current_date-1 where user_id='${A}';
    update paper_accounts set today_realized_pnl_usd=0,last_reset_date=current_date where user_id='${A}'`);
  assert.equal((await observe(A)).locked, false);
  // Service can upsert reports, authenticated readers only see their book.
  await db.exec(`insert into book_daily_pnl(user_id,day,status,report) values
    ('${A}',current_date,'unknown','{}'),('${B}',current_date,'partial','{}');
    reset role; set role authenticated;`);
  assert.equal((await query('select * from book_daily_pnl')).length, 1);
  // Existing owner-authorized account writes still work with the private trigger.
  await db.exec(`update paper_accounts set today_realized_pnl_usd=55 where user_id='${A}'`);
  let rejected = false;
  try { await observe(A); } catch { rejected = true; }
  assert.equal(rejected, true);
  rejected = false;
  try { await db.exec(`update book_daily_pnl set status='complete'`); } catch { rejected = true; }
  assert.equal(rejected, true);
  await db.exec('reset role');
  assert.equal((await observe(A)).locked, true);
  assert.equal((await query(`select has_function_privilege('anon','trezo_private.latch_banked_goal()','execute') as allowed`))[0].allowed, false);
  assert.equal((await query(`select has_function_privilege('anon','observe_daily_goal(uuid,numeric,text,boolean)','execute') as allowed`))[0].allowed, false);
  console.log('PASS: default-on switch; bank/giveback; first-refusal dedupe; book isolation; restart persistence; rollover; service writes; owner RLS; blocked public RPC/writes.');
} finally { await db.close(); }
