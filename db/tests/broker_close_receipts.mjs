/** Run: PGLITE_MODULE=/absolute/path/to/@electric-sql/pglite/dist/index.js node db/tests/broker_close_receipts.mjs
 * Real PostgreSQL semantics in an isolated WASM database. No network or broker.
 * Tests transaction rollback and sequential CAS conflicts, not multi-connection concurrency.
 */
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
process.on('uncaughtException', error => {
 console.error(`${error.name}: ${error.message}${error.where ? ` (${error.where})` : ''}${error.position ? ` at SQL offset ${error.position}` : ''}`);
 process.exit(1);
});
const moduleName = process.env.PGLITE_MODULE;
if (!moduleName) throw new Error('Set PGLITE_MODULE to an installed PGlite module path');
const {PGlite} = await import(pathToFileURL(moduleName).href);
const db = new PGlite();
await db.exec(`
create role anon; create role authenticated; create role service_role bypassrls;
create table public.schema_migrations(version text primary key,assumed boolean,notes text);
create table public.trading_accounts(account_key uuid primary key);
create table public.paper_accounts(
 user_id uuid primary key references public.trading_accounts(account_key),
 current_cash_usd numeric(14,2) not null default 1000,
 ytd_realized_pnl_usd numeric(14,2) not null default 0,
 today_realized_pnl_usd numeric(14,2) not null default 0,
 week_realized_pnl_usd numeric(14,2) not null default 0,
 last_reset_date date not null default (now() at time zone 'UTC')::date,
 week_start_date date not null default (now() at time zone 'UTC')::date,
 consecutive_losses integer default 0, updated_at timestamptz default now());
create table public.paper_positions(
 id uuid primary key default gen_random_uuid(), user_id uuid references public.trading_accounts(account_key),
 ticker text not null, asset_type text not null check(asset_type in ('stock','crypto','option')),
 side text not null check(side in ('long','short')), quantity numeric(30,12) not null check(quantity>0),
 entry_price numeric(20,8) not null check(entry_price>0), entry_at timestamptz not null default now()-interval '1 day',
 stop_price numeric(20,8),target_price numeric(20,8),
 status text not null default 'open' check(status in ('open','closed_stop','closed_target','closed_manual','closed_time','closed_eod','closed_partial','closed_expired','closed_adopted')),
 exit_price numeric(20,8),exit_at timestamptz,realized_pnl_usd numeric(14,4),
 fees_usd numeric(14,4) not null default 0,strategy text,source_payload jsonb,broker text,broker_order_id text);
create table public.trade_outcomes(
 id uuid primary key default gen_random_uuid(),user_id uuid not null,position_id uuid,
 source_table text,ticker text not null,asset_type text,side text,strategy text,direction text,
 entry_payload jsonb,exit_reason text,status text,entry_price numeric(20,8),exit_price numeric(20,8),
 quantity numeric(20,8),realized_pnl_usd numeric(14,4),opened_at timestamptz,closed_at timestamptz);
grant usage on schema public to service_role;
grant select,insert,update on all tables in schema public to service_role;
`);
await db.exec(await readFile(new URL('../migrations/20260918155909_broker_close_receipts.sql', import.meta.url), 'utf8'));
const book = '10000000-0000-0000-0000-000000000001';
const book2 = '10000000-0000-0000-0000-000000000002';
await db.query('insert into trading_accounts values ($1),($2)', [book,book2]);
await db.query('insert into paper_accounts(user_id) values ($1),($2)', [book,book2]);
const known = {entry_basis_verified:true,entry_fees_known:true};
async function position({user=book, ticker='SOL', qty=5, price=100, fees=0, side='long', asset='crypto', payload=known}={}) {
 const {rows} = await db.query(`insert into paper_positions(user_id,ticker,asset_type,side,quantity,entry_price,fees_usd,broker,source_payload)
 values ($1,$2,$3,$4,$5,$6,$7,'alpaca',$8) returning id`, [user,ticker,asset,side,qty,price,fees,JSON.stringify(payload)]);
 return rows[0].id;
}
const receipt = (id, qty, avg, extra={}) => ({id,symbol:'SOL/USD',side:'sell',status:'filled',
 filled_qty:String(qty),filled_avg_price:String(avg),filled_at:new Date().toISOString(),...extra});
async function close(id, r, user=book, reason='manual') {
 const {rows} = await db.query('select record_broker_close($1,$2,$3,$4) as result', [user,id,JSON.stringify(r),reason]);
 return rows[0].result;
}
async function row(id) {return (await db.query('select * from paper_positions where id=$1',[id])).rows[0];}
async function balance(user=book) {return (await db.query('select * from paper_accounts where user_id=$1',[user])).rows[0];}
async function count(table) {return Number((await db.query(`select count(*) as n from ${table}`)).rows[0].n);}
let cases = 0;

// 1: cumulative receipt deltas, retained entry fees, exact final price, no synthetic slippage.
const p = await position({fees:5});
let r = await close(p, receipt('partial-to-full',2,110,{status:'partially_filled'}),book,'profit_step');
assert.equal(r.realized_pnl_usd,18); assert.equal(r.remaining_qty,3); assert.equal(r.pending,true);
assert.equal(r.pnl_provisional,true); assert.equal(Number((await row(p)).fees_usd),3);
r = await close(p, receipt('partial-to-full',5,112,{fee_usd:'0'}),book,'profit_step');
assert.equal(r.realized_pnl_usd,37); assert.equal(r.remaining_qty,0); assert.equal(r.pnl_provisional,false);
assert.ok(Math.abs(Number(r.fill_price)-113.33333333333333)<1e-8);
assert.equal(Number((await balance()).ytd_realized_pnl_usd),55);
assert.equal(Number((await balance()).current_cash_usd),1000);
assert.equal(await count('broker_close_receipts'),1); assert.equal(await count('trade_outcomes'),2);
assert.equal(Number((await db.query('select count(*) n from trade_outcomes where position_id=$1 and exit_reason=$2',[p,'profit_step'])).rows[0].n),2);
cases++;

// 2: repeated full receipt and unknown-to-known fee confirmation are idempotent.
r = await close(p, receipt('partial-to-full',5,112,{fee_usd:'0'}));
assert.equal(r.duplicate,true); assert.equal(r.realized_pnl_usd,0); assert.equal(r.fees_complete,true);
assert.equal(await count('trade_outcomes'),2); assert.equal(Number((await balance()).ytd_realized_pnl_usd),55);
cases++;

// 3: late known cumulative fee amends the existing fill/outcome, exactly once.
r = await close(p, receipt('partial-to-full',5,112,{fee_usd:'2'}));
assert.equal(r.realized_pnl_usd,-2); assert.equal(r.pnl_provisional,false);
assert.equal(Number((await balance()).ytd_realized_pnl_usd),53);
assert.equal(Number((await row(p)).fees_usd),5);
assert.equal((await row(p)).source_payload.broker_accounting.exit_fees_known,true);
r = await close(p, receipt('partial-to-full',5,112,{fee_usd:'2'}));
assert.equal(r.duplicate,true); assert.equal(Number((await balance()).ytd_realized_pnl_usd),53);
assert.equal(await count('trade_outcomes'),2); cases++;

// 4: a short realizes the reverse price move without touching snapshot cash.
const short = await position({ticker:'AAPL',asset:'stock',side:'short',qty:3});
r = await close(short,receipt('short',3,90,{symbol:'AAPL',side:'buy',fee_usd:'0'}));
assert.equal(r.realized_pnl_usd,30); assert.equal(Number((await balance()).current_cash_usd),1000); cases++;

// 5: account scope is part of identity; the same order ID in another book is distinct.
const other = await position({user:book2,qty:1});
await close(other,receipt('short',1,105,{fee_usd:'0'}),book2);
assert.equal(Number((await balance(book2)).ytd_realized_pnl_usd),5);
await assert.rejects(close(other,receipt('wrong-book',1,105),book),/broker_position_mismatch/);
const stolen = await position({qty:1});
await assert.rejects(close(stolen,receipt('short',1,105)),/already_claimed_by_another_position/); cases++;

// 6: invalid evidence must not alter position, account, outcomes, or receipts.
const before = JSON.stringify(await balance());
const outcomesBefore = await count('trade_outcomes');
for (const changes of [{filled_qty:'2'}, {side:'buy'}, {symbol:'BTC/USD'}, {status:'accepted'},
 {filled_avg_price:'NaN'}, {filled_qty:'0.1234567890123'}, {filled_at:'2000-01-01T00:00:00Z'}]) {
 await assert.rejects(close(stolen,receipt('invalid',1,105,changes)));
}
assert.equal((await row(stolen)).status,'open'); assert.equal(JSON.stringify(await balance()),before);
assert.equal(await count('trade_outcomes'),outcomesBefore); cases++;

// 7: database error after a position mutation rolls the entire RPC back.
await db.exec(`create function test_fail_outcome() returns trigger language plpgsql as $$ begin raise exception 'injected_outcome_failure'; end $$;
create trigger fail_outcome before insert on trade_outcomes for each row execute function test_fail_outcome();`);
await assert.rejects(close(stolen,receipt('rollback',1,110)),/injected_outcome_failure/);
assert.equal((await row(stolen)).status,'open'); assert.equal(JSON.stringify(await balance()),before);
assert.equal(Number((await db.query("select count(*) n from broker_close_receipts where order_id='rollback'")).rows[0].n),0);
await db.exec('drop trigger fail_outcome on trade_outcomes; drop function test_fail_outcome();'); cases++;

// Also fail after account/outcome updates, at the final receipt insert.
await db.exec(`create function test_fail_receipt() returns trigger language plpgsql as $$ begin raise exception 'injected_receipt_failure'; end $$;
create trigger fail_receipt before insert on broker_close_receipts for each row execute function test_fail_receipt();`);
await assert.rejects(close(stolen,receipt('late-rollback',1,110)),/injected_receipt_failure/);
assert.equal((await row(stolen)).status,'open'); assert.equal(JSON.stringify(await balance()),before);
assert.equal(await count('trade_outcomes'),outcomesBefore);
await db.exec('drop trigger fail_receipt on broker_close_receipts; drop function test_fail_receipt();'); cases++;

// 8: claims compare exact current intent. Ambiguous duplicate symbols cannot be liquidated.
const claimPos = await position({ticker:'BTC',qty:2});
const claim = async (id, expected, pending) => (await db.query('select claim_broker_exit($1,$2,$3,$4) result',
 [book,id,expected===null?null:JSON.stringify(expected),pending===null?null:JSON.stringify(pending)])).rows[0].result;
const pending = {intent_id:'intent-one',order_id:'daily-order',quantity:2};
assert.equal((await claim(claimPos,null,pending)).claimed,true);
assert.equal((await claim(claimPos,null,{intent_id:'second'})).claimed,false);
r = await close(claimPos,receipt('daily-order',1,110,{symbol:'BTC/USD',status:'done_for_day'}));
assert.equal(r.pending,true); assert.equal((await row(claimPos)).source_payload.broker_exit_pending.order_id,'daily-order');
r = await close(claimPos,receipt('daily-order',1,110,{symbol:'BTC/USD',status:'canceled'}));
assert.equal(r.duplicate,true); assert.equal(r.pending,false); assert.equal(r.remaining_qty,1);
assert.equal((await row(claimPos)).source_payload.broker_exit_pending,undefined);
const duplicate = await position({ticker:'BTCUSD',qty:1});
await assert.rejects(claim(claimPos,null,{intent_id:'unsafe'}),/broker_exit_ownership_ambiguous/);
await assert.rejects(claim(duplicate,null,{intent_id:'unsafe'}),/broker_exit_ownership_ambiguous/); cases++;

// 9: sub-cent deltas and 12-decimal quantities survive exact cumulative accounting.
const micro = await position({ticker:'LINK',qty:'0.000000000002',price:1});
r = await close(micro,receipt('micro', '0.000000000001', 2, {symbol:'LINK/USD',status:'partially_filled'}));
assert.equal(r.remaining_qty,1e-12);
assert.equal((await db.query('select quantity from trade_outcomes where position_id=$1',[micro])).rows[0].quantity,'0.000000000001');
const pennies = await position({ticker:'NVDA',asset:'stock',qty:3});
const start = Number((await balance()).ytd_realized_pnl_usd);
for (let q=1;q<=3;q++) await close(pennies,receipt('pennies',q,'100.004',{symbol:'NVDA',status:q===3?'filled':'partially_filled',fee_usd:'0'}));
assert.ok(Math.abs(Number((await balance()).ytd_realized_pnl_usd)-start-0.012)<1e-10); cases++;

// 10: older fees stay in the original fill period, never poll-date today/week.
const historic = await position({ticker:'MSFT',asset:'stock',qty:1});
await db.query("update paper_positions set entry_at=now()-interval '30 days' where id=$1",[historic]);
const oldAt = new Date(Date.now()-10*86400000).toISOString();
const todayBefore = Number((await balance()).today_realized_pnl_usd);
await close(historic,receipt('historic',1,110,{symbol:'MSFT',filled_at:oldAt}));
await close(historic,receipt('historic',1,110,{symbol:'MSFT',filled_at:new Date().toISOString(),fee_usd:'1'}));
assert.equal(Number((await balance()).today_realized_pnl_usd),todayBefore); cases++;

// 11: full-trade loss streak includes earlier partial gains, not just the last slice.
const streak = await position({ticker:'AMD',asset:'stock',qty:2});
await close(streak,receipt('streak',1,120,{symbol:'AMD',status:'partially_filled'}));
await close(streak,receipt('streak',2,105,{symbol:'AMD'})); // +20 then -10: profitable whole trade
assert.equal(Number((await balance()).consecutive_losses),0); cases++;

// 12: paper/options receipt consumers share order identity under the book lock.
await db.exec(`create table option_close_receipts(user_id uuid,broker text,order_id text);
grant select on option_close_receipts to service_role;`);
await db.query("insert into option_close_receipts values ($1,'alpaca','owned-by-options')",[book]);
await assert.rejects(close(stolen,receipt('owned-by-options',1,110)),/already_claimed_by_options/);
assert.equal((await row(stolen)).status,'open'); cases++;

// 13: service-role-only, invoker-security RPCs, and receipt RLS.
const security = await db.query("select proname,prosecdef from pg_proc where proname in ('record_broker_close','claim_broker_exit')");
assert.equal(security.rows.length,2); assert.ok(security.rows.every(x=>x.prosecdef===false));
assert.equal((await db.query("select relrowsecurity from pg_class where oid='broker_close_receipts'::regclass")).rows[0].relrowsecurity,true);
for (const role of ['anon','authenticated']) {
 await db.exec(`set role ${role}`);
 await assert.rejects(close(p,receipt('partial-to-full',5,112,{fee_usd:'2'})),/permission denied/);
 await db.exec('reset role');
}
await db.exec('set role service_role');
assert.equal((await close(p,receipt('partial-to-full',5,112,{fee_usd:'2'}))).duplicate,true);
await db.exec('reset role'); cases++;
await db.close();
console.log(`${cases} PostgreSQL broker receipt integration cases passed (isolated PGlite; no concurrent-connection claim).`);
