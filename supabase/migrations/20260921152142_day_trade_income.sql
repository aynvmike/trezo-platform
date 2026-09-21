-- Entry-only protections and read-only broker scorecards. No history rewrite.
begin;
alter table public.bot_settings add column if not exists goal_lock_enabled boolean not null default true;

create table public.book_goal_locks (
  user_id uuid not null references public.trading_accounts(account_key),
  day date not null,
  goal numeric not null check(goal > 0),
  label text not null,
  locked_at timestamptz,
  realized_at_lock numeric,
  announced_at timestamptz,
  primary key(user_id, day)
);
alter table public.book_goal_locks enable row level security;
revoke all on public.book_goal_locks from public,anon,authenticated;
grant select,insert,update on public.book_goal_locks to service_role;

-- Trigger observes EVERY account-counter writer, including partial exits.
-- A day's threshold is armed by the entry gate before it permits a trade.
-- Account resets also run under the authenticated owner's existing RLS.
-- Keep the trigger-only writer private so those permitted updates can latch
-- protective state without giving clients permission to edit/unlock it.
create schema if not exists trezo_private;
revoke all on schema trezo_private from public,anon,authenticated;
create function trezo_private.latch_banked_goal() returns trigger language plpgsql
security definer set search_path='' as $$
begin
  if tg_table_schema<>'public' or tg_table_name<>'paper_accounts' or tg_op<>'UPDATE'
     or new.user_id is distinct from old.user_id then
    raise exception 'invalid goal trigger context';
  end if;
  if new.last_reset_date=(now() at time zone 'UTC')::date then
    update public.book_goal_locks set locked_at=now(),realized_at_lock=new.today_realized_pnl_usd
      where user_id=new.user_id and day=new.last_reset_date and locked_at is null
        and new.today_realized_pnl_usd>=goal;
  end if;
  return new;
end $$;
revoke all on function trezo_private.latch_banked_goal() from public,anon,authenticated;
create trigger latch_banked_goal after update of today_realized_pnl_usd on public.paper_accounts
for each row execute function trezo_private.latch_banked_goal();

create function public.observe_daily_goal(p_user_id uuid,p_goal numeric,p_label text,p_announce boolean default false)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare
  a public.paper_accounts%rowtype;
  g public.book_goal_locks%rowtype;
  d date := (now() at time zone 'UTC')::date;
  first_refusal boolean := false;
begin
  if p_goal is null or p_goal<=0 or p_goal::text in ('NaN','Infinity','-Infinity') then
    raise exception 'invalid goal';
  end if;
  select * into a from public.paper_accounts where user_id=p_user_id for update;
  if not found or a.last_reset_date is distinct from d then
    raise exception 'account counters unavailable';
  end if;
  insert into public.book_goal_locks(user_id,day,goal,label)
    values(p_user_id,d,p_goal,p_label) on conflict(user_id,day) do update set
      goal=case when book_goal_locks.locked_at is null then excluded.goal else book_goal_locks.goal end,
      label=case when book_goal_locks.locked_at is null then excluded.label else book_goal_locks.label end;
  update public.book_goal_locks set locked_at=now(),realized_at_lock=a.today_realized_pnl_usd
    where user_id=p_user_id and day=d and locked_at is null
      and a.last_reset_date=d and a.today_realized_pnl_usd>=goal;
  select * into g from public.book_goal_locks where user_id=p_user_id and day=d for update;
  if p_announce and g.locked_at is not null and g.announced_at is null then
    update public.book_goal_locks set announced_at=now() where user_id=p_user_id and day=d;
    first_refusal := true;
  end if;
  return jsonb_build_object('ok',true,'locked',g.locked_at is not null,
    'goal',g.goal,'label',g.label,'day',d,'realized_at_lock',g.realized_at_lock,'first_refusal',first_refusal);
end $$;
revoke all on function public.observe_daily_goal(uuid,numeric,text,boolean) from public,anon,authenticated;
grant execute on function public.observe_daily_goal(uuid,numeric,text,boolean) to service_role;

create table public.book_daily_pnl (
  user_id uuid not null references public.trading_accounts(account_key),
  day date not null,
  status text not null check(status in ('complete','partial','unknown')),
  lanes jsonb not null default '{}',
  trades integer, day_trades integer, win_rate numeric,
  average_win numeric, average_loss numeric, profit_factor numeric, expectancy numeric,
  gross_pnl_usd numeric, fees_usd numeric, net_pnl_usd numeric,
  friction_share_of_equity numeric, unexplained_usd numeric,
  report jsonb not null,
  generated_at timestamptz not null default now(),
  primary key(user_id,day)
);
alter table public.book_daily_pnl enable row level security;
revoke all on public.book_daily_pnl from public,anon,authenticated;
grant select,insert,update on public.book_daily_pnl to service_role;
grant select on public.book_daily_pnl to authenticated;
create policy book_daily_pnl_owner_read on public.book_daily_pnl
for select to authenticated using(user_id in (select public.my_account_keys()));
commit;
