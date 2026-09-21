// Offline PostgreSQL regression tests. Install @electric-sql/pglite externally
// or set PGLITE_MODULE to its dist/index.js. No production connection is used.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const { PGlite } = await import(process.env.PGLITE_MODULE || '@electric-sql/pglite');
const db = new PGlite();
await db.exec(`
set timezone='UTC';
create role anon; create role authenticated; create role service_role bypassrls;
create table public.schema_migrations(version text primary key, applied_at timestamptz default now(), assumed boolean default false, notes text);
create table public.trading_accounts(account_key uuid primary key);
create table public.paper_accounts(user_id uuid primary key references trading_accounts(account_key),
 current_cash_usd numeric(14,2) default 10000, ytd_realized_pnl_usd numeric(16,4) default 0,
 today_realized_pnl_usd numeric(16,4) default 0,week_realized_pnl_usd numeric(16,4) default 0,
 last_reset_date date default current_date,week_start_date date default current_date,updated_at timestamptz default now());
create table public.paper_positions(id uuid primary key default gen_random_uuid(),user_id uuid not null,
 broker text,asset_type text,ticker text,status text);
create table public.options_positions(id uuid primary key default gen_random_uuid(),
 user_id uuid not null references trading_accounts(account_key),underlying text not null,
 strategy text not null,direction text not null default 'income',option_type text,strike numeric(20,4),expiration date,
 contracts integer not null check(contracts>0),net_premium_usd numeric(14,4) not null,
 modeled_iv numeric(6,4),legs jsonb not null default '[]',status text not null default 'open'
 check(status in ('open','closed_expired','closed_assigned','closed_manual','closed_profit')),
 realized_pnl_usd numeric(14,4),opened_at timestamptz not null default now()-interval '1 day',closed_at timestamptz,
 notes text,created_at timestamptz default now(),updated_at timestamptz default now());
create table public.trade_outcomes(id uuid primary key default gen_random_uuid(),user_id uuid not null,
 position_id uuid,source_table text,ticker text not null,asset_type text,side text,strategy text,direction text,
 entry_payload jsonb,exit_reason text,status text,entry_price numeric(20,8),exit_price numeric(20,8),
 quantity numeric(30,12),realized_pnl_usd numeric(14,4),opened_at timestamptz,closed_at timestamptz);
create table public.broker_close_receipts(user_id uuid,broker text,order_id text,primary key(user_id,broker,order_id));
grant usage on schema public to service_role;
grant all on all tables in schema public to service_role;
`);
const migration = await readFile(new URL('../migrations/20260918160730_option_close_receipts.sql', import.meta.url), 'utf8');
await db.exec(migration);
const A = '00000000-0000-4000-8000-000000000001';
const B = '00000000-0000-4000-8000-000000000002';
const P = '10000000-0000-4000-8000-000000000001';
const Q = '10000000-0000-4000-8000-000000000002';
const OCC = 'XYZ261218P00050000';
const stamp = new Date(Date.now() - 1000).toISOString();
const pending = (id='order-a', qty=5) => ({intent_id:'intent-a',started_at:stamp,reason:'harvest',quantity:qty,symbol:OCC,side:'buy',order_id:id});
const receipt = (qty=3, status='partially_filled', avg='0.4', id='order-a') =>
 ({id,symbol:OCC,side:'buy',status,filled_qty:String(qty),filled_avg_price:avg,filled_at:stamp});
const query = async (sql,args=[]) => (await db.query(sql,args)).rows;
const one = async (sql,args=[]) => (await query(sql,args))[0];
const claim = async (old,next,uid=A,pid=P) => (await one('select claim_option_broker_exit($1,$2,$3::jsonb,$4::jsonb) as r', [uid,pid,old==null?null:JSON.stringify(old),next==null?null:JSON.stringify(next)])).r;
const record = async (r,uid=A,pid=P) => (await one('select record_option_broker_close($1,$2,$3::jsonb,$4) as r',[uid,pid,JSON.stringify(r),'harvest'])).r;
async function reset({premium=500,contracts=5,meta=null}={}) {
 await db.exec('truncate option_close_receipts,broker_close_receipts,trade_outcomes,options_positions,paper_positions,paper_accounts,trading_accounts cascade');
 await db.query('insert into trading_accounts values($1),($2)',[A,B]);
 await db.query('insert into paper_accounts(user_id,last_reset_date,week_start_date) values($1,$3::timestamptz::date,$3::timestamptz::date),($2,$3::timestamptz::date,$3::timestamptz::date)',[A,B,stamp]);
 await db.query(`insert into options_positions(id,user_id,underlying,strategy,option_type,strike,expiration,contracts,net_premium_usd,notes,broker_accounting)
 values($1,$2,'XYZ','wheel_csp','put',50,'2026-12-18',$3,$4,'Placed via Alpaca - original provenance',$5::jsonb)`,[P,A,contracts,premium,meta==null?null:JSON.stringify(meta)]);
}
async function unchanged() {
 const p=await one('select * from options_positions where id=$1',[P]);
 assert.equal(p.contracts,5); assert.equal(p.status,'open');
 assert.equal((await one('select count(*)::int n from option_close_receipts')).n,0);
 assert.equal(Number((await one('select ytd_realized_pnl_usd from paper_accounts where user_id=$1',[A])).ytd_realized_pnl_usd),0);
}
const tests=[];
function test(name,fn) { tests.push([name,fn]); }

test('durable compare-and-swap admits one submitter and rejects changed intent',async()=>{
 await reset();
 const unknown=pending(null);
 const replies=await Promise.all([claim(null,unknown),claim(null,{...unknown,intent_id:'racer'})]);
 assert.equal(replies.filter(r=>r.claimed).length,1);
 assert.equal((await claim(null,pending())).claimed,false);
 await assert.rejects(()=>claim(unknown,{...pending(),quantity:4}),/intent_changed/);
 assert.equal((await claim(unknown,pending())).claimed,true);
 assert.deepEqual((await one('select broker_exit_pending from options_positions where id=$1',[P])).broker_exit_pending,pending());
 await unchanged();
});

test('partial receipt slices only actual contracts and cumulative fills dedupe',async()=>{
 await reset(); await claim(null,pending());
 const first=await record(receipt());
 assert.equal(first.closed_qty,3); assert.equal(first.remaining_qty,2); assert.equal(first.realized_pnl_usd,180); assert.equal(first.pending,true);
 const p=await one('select * from options_positions where id=$1',[P]);
 assert.equal(p.contracts,2); assert.equal(Number(p.net_premium_usd),200); assert.equal(p.status,'open');
 assert.deepEqual(p.broker_exit_pending,pending());
 const slice=await one('select * from options_positions where id=$1',[first.slice_id]);
 assert.equal(slice.contracts,3); assert.equal(Number(slice.net_premium_usd),300);
 assert.equal(Number(slice.realized_pnl_usd),180); assert.equal(slice.notes,p.notes);
 assert.equal(slice.broker_accounting.pnl_provisional,true);
 const repeat=await record(receipt());
 assert.equal(repeat.duplicate,true); assert.equal(repeat.realized_pnl_usd,0);
 const last=await record(receipt(5,'filled','0.5'));
 assert.equal(last.closed_qty,2); assert.equal(last.remaining_qty,0); assert.equal(last.fill_price,0.65);
 assert.equal(last.realized_pnl_usd,70); assert.equal(last.pending,false);
 const book=await one('select * from paper_accounts where user_id=$1',[A]);
 assert.equal(Number(book.ytd_realized_pnl_usd),250); assert.equal(Number(book.today_realized_pnl_usd),250);
 assert.equal(Number(book.week_realized_pnl_usd),250); assert.equal(Number(book.current_cash_usd),10000);
 assert.equal((await one('select count(*)::int n from trade_outcomes')).n,2);
 assert.equal((await one('select broker_exit_pending from options_positions where id=$1',[P])).broker_exit_pending,null);
 assert.equal((await record(receipt(5,'filled','0.5'))).duplicate,true);
});

test('done-for-day stays pending; terminal same-quantity poll clears without recounting',async()=>{
 await reset();await claim(null,pending());await record(receipt());
 const paused=await record(receipt(3,'done_for_day'));
 assert.equal(paused.pending,true);assert.equal(paused.duplicate,true);
 assert.notEqual((await one('select broker_exit_pending from options_positions where id=$1',[P])).broker_exit_pending,null);
 const terminal=await record(receipt(3,'canceled'));
 assert.equal(terminal.pending,false);assert.equal(terminal.duplicate,true);
 assert.equal((await one('select broker_exit_pending from options_positions where id=$1',[P])).broker_exit_pending,null);
 const next={...pending('order-b',2),intent_id:'intent-b'};
 assert.equal((await claim(null,next)).claimed,true);
 assert.equal((await record(receipt(2,'filled','0.8','order-b'))).realized_pnl_usd,40);
 assert.equal(Number((await one('select ytd_realized_pnl_usd from paper_accounts where user_id=$1',[A])).ytd_realized_pnl_usd),220);
});

test('late cumulative fees adjust exactly once and retain provisional entry basis',async()=>{
 await reset();await claim(null,pending());await record(receipt(5,'filled','0.5'));
 const late=await record({...receipt(5,'filled','0.5'),fee_usd:'5'});
 assert.equal(late.realized_pnl_usd,-5);assert.equal(late.closed_qty,0);assert.equal(late.pnl_provisional,true);
 assert.equal((await record({...receipt(5,'filled','0.5'),fee_usd:'5'})).realized_pnl_usd,0);
 assert.equal((await one('select count(*)::int n from trade_outcomes')).n,1);
 assert.equal(Number((await one('select ytd_realized_pnl_usd from paper_accounts where user_id=$1',[A])).ytd_realized_pnl_usd),245);
 await assert.rejects(()=>record({...receipt(5,'filled','0.5'),fee_usd:'4'}),/regressed/);
});

test('a long close prorates debit and known fees from actual sale receipt',async()=>{
 await reset({premium:-500,meta:{entry_basis_verified:true,entry_fees_known:true,entry_fee_usd:5}});
 const intent={...pending(),side:'sell'}; await claim(null,intent);
 const r=await record({...receipt(3,'partially_filled','1.5'),side:'sell',fee_usd:'3'});
 assert.equal(r.realized_pnl_usd,144); assert.equal(r.pnl_provisional,false);
 const p=await one('select * from options_positions where id=$1',[P]);
 assert.equal(Number(p.net_premium_usd),-200);assert.equal(p.broker_accounting.entry_fee_usd,2);
});

test('known fees on earlier partial fill cannot certify newer fills',async()=>{
 await reset({meta:{entry_basis_verified:true,entry_fees_known:true,entry_fee_usd:0}});
 await claim(null,pending());
 assert.equal((await record({...receipt(),fee_usd:'1'})).pnl_provisional,false);
 assert.equal((await record(receipt(5,'filled','0.5'))).pnl_provisional,true);
 assert.equal((await record(receipt(5,'filled','0.5'))).pnl_provisional,true);
 assert.equal((await record({...receipt(5,'filled','0.5'),fee_usd:'2'})).pnl_provisional,false);
 assert.equal((await record(receipt(5,'filled','0.5'))).pnl_provisional,false);
});

test('unclaimed partial receipts are refused instead of silently creating ownership',async()=>{
 await reset();await assert.rejects(()=>record(receipt()),/requires_intent/);await unchanged();
});

test('cross-book requests fail without touching either account',async()=>{
 await reset();await claim(null,pending());
 await assert.rejects(()=>record(receipt(),B),/position_mismatch/);
 await assert.rejects(()=>claim(null,pending(),B),/position_not_open/);
 await unchanged();
 assert.equal(Number((await one('select ytd_realized_pnl_usd from paper_accounts where user_id=$1',[B])).ytd_realized_pnl_usd),0);
});

test('wrong symbol, side, lifecycle, quantity and nonfinite values never settle',async()=>{
 for(const bad of [
  {symbol:'OTHER'}, {side:'sell'}, {status:'new'}, {filled_qty:'0'}, {filled_qty:'1.5'},
  {filled_qty:'6'}, {filled_avg_price:'NaN'}, {filled_avg_price:'Infinity'}, {fee_usd:'-1'},
  {filled_at:'2000-01-01T00:00:00Z'}, {id:'different-order'},
 ]) {
  await reset();await claim(null,pending());
  await assert.rejects(()=>record({...receipt(),...bad}));await unchanged();
 }
});

test('post-position failure rolls back slice, parent, receipt, outcome and counters',async()=>{
 await reset();await claim(null,pending());
 await db.exec('alter table trade_outcomes add constraint inject_failure check(false)');
 try { await assert.rejects(()=>record(receipt()),/inject_failure/); }
 finally { await db.exec('alter table trade_outcomes drop constraint inject_failure'); }
 await unchanged();
 assert.equal((await one('select count(*)::int n from options_positions')).n,1);
 assert.deepEqual((await one('select broker_exit_pending from options_positions where id=$1',[P])).broker_exit_pending,pending());
});

test('reconciled full receipt without pending is allowed and idempotent',async()=>{
 await reset();const result=await record(receipt(5,'filled','0.5'));
 assert.equal(result.remaining_qty,0);assert.equal(result.realized_pnl_usd,250);
 assert.equal((await record(receipt(5,'filled','0.5'))).duplicate,true);
});

test('duplicate option managers, paper managers and paper-claimed receipts refuse ownership',async()=>{
 await reset();
 await db.query(`insert into options_positions(id,user_id,underlying,strategy,option_type,strike,expiration,contracts,net_premium_usd)
 values($1,$2,'XYZ','wheel_csp','put',50,'2026-12-18',5,500)`,[Q,A]);
 await assert.rejects(()=>claim(null,pending()),/ownership_ambiguous/);
 await assert.rejects(()=>record(receipt(5,'filled')),/ownership_ambiguous/);
 await reset();
 await db.query("insert into paper_positions(user_id,broker,asset_type,ticker,status) values($1,'alpaca','option',$2,'open')",[A,OCC]);
 await assert.rejects(()=>claim(null,pending()),/ownership_ambiguous/);
 await reset();
 await db.query("insert into broker_close_receipts values($1,'alpaca','order-a')",[A]);
 await assert.rejects(()=>record(receipt(5,'filled')),/claimed_by_paper_ledger/);
 await unchanged();
});

test('order cannot be claimed by a later lifecycle in the same book',async()=>{
 await reset();await record(receipt(5,'filled'));
 await db.query(`insert into options_positions(id,user_id,underlying,strategy,option_type,strike,expiration,contracts,net_premium_usd)
 values($1,$2,'XYZ','wheel_csp','put',50,'2026-12-18',5,500)`,[Q,A]);
 await assert.rejects(()=>record(receipt(5,'filled'),A,Q),/already_claimed/);
 assert.equal((await one('select count(*)::int n from trade_outcomes')).n,1);
});

test('service-only invoker RPCs and RLS receipt table have no public grants',async()=>{
 const privileges=await one(`select
 has_function_privilege('anon','public.record_option_broker_close(uuid,uuid,jsonb,text)','execute') as anon,
 has_function_privilege('authenticated','public.claim_option_broker_exit(uuid,uuid,jsonb,jsonb)','execute') as auth,
 has_function_privilege('service_role','public.record_option_broker_close(uuid,uuid,jsonb,text)','execute') as service,
 has_table_privilege('anon','public.option_close_receipts','select') as table_anon,
 (select relrowsecurity from pg_class where oid='public.option_close_receipts'::regclass) as rls,
 (select bool_or(prosecdef) from pg_proc where proname in ('claim_option_broker_exit','record_option_broker_close')) as definer`);
 assert.deepEqual(privileges,{anon:false,auth:false,service:true,table_anon:false,rls:true,definer:false});
 await reset();await db.exec('set role service_role');
 try { assert.equal((await claim(null,pending())).claimed,true);assert.equal((await record(receipt())).closed_qty,3); }
 finally { await db.exec('reset role'); }
 const tracked=await one("select assumed from schema_migrations where version='20260918160730_option_close_receipts'");
 assert.equal(tracked.assumed,false);
});

let passed=0;
try {
 for(const [name,fn] of tests) { await fn();passed++;console.log(`PASS ${name}`); }
 console.log(`${passed}/${tests.length} option SQL tests passed`);
} finally { await db.close(); }
