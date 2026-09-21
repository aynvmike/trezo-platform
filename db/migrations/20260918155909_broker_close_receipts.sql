-- Generated with Supabase CLI; NOT APPLIED to production. Install and verify
-- this transaction before deploying the runtime changes.
-- No history is rewritten. Runtime refuses broker accounting without these RPCs.
begin;

-- Match position P&L precision so partial fills cannot round away cents on
-- every poll. Integer capacity is unchanged; existing values are preserved.
alter table public.paper_accounts
  alter column ytd_realized_pnl_usd type numeric(16,4),
  alter column today_realized_pnl_usd type numeric(16,4),
  alter column week_realized_pnl_usd type numeric(16,4);
alter table public.trade_outcomes alter column quantity type numeric(30,12);

create table if not exists public.broker_close_receipts (
  user_id uuid not null references public.trading_accounts(account_key),
  broker text not null check (broker = 'alpaca'),
  order_id text not null,
  position_id uuid not null references public.paper_positions(id),
  cumulative_qty numeric(30,12) not null default 0,
  cumulative_notional numeric not null default 0,
  cumulative_fee_usd numeric,
  last_slice_id uuid references public.paper_positions(id),
  last_outcome_id uuid,
  filled_at timestamptz not null,
  receipt jsonb not null,
  updated_at timestamptz not null default now(),
  primary key (user_id, broker, order_id)
);
alter table public.broker_close_receipts enable row level security;
revoke all on public.broker_close_receipts from public, anon, authenticated;
grant select, insert, update on public.broker_close_receipts to service_role;

-- Atomic ownership of the submit attempt, including crash/unknown-submit state.
create or replace function public.claim_broker_exit(
  p_user_id uuid, p_position_id uuid, p_expected_pending jsonb, p_pending jsonb
) returns jsonb language plpgsql security invoker set search_path = '' as $$
declare
  v_pos public.paper_positions%rowtype;
  v_current jsonb;
begin
  perform 1 from public.paper_accounts where user_id=p_user_id for update;
  if not found then raise exception 'broker_book_missing'; end if;
  select * into v_pos from public.paper_positions
    where id=p_position_id and user_id=p_user_id for update;
  if not found or v_pos.broker is distinct from 'alpaca' or v_pos.status <> 'open' then
    raise exception 'broker_position_not_open';
  end if;
  v_current := v_pos.source_payload->'broker_exit_pending';
  if v_current is distinct from p_expected_pending then
    return jsonb_build_object('ok',true,'claimed',false,'pending',v_current);
  end if;
  if p_expected_pending is null and p_pending is not null and
    (select count(*) from public.paper_positions where user_id=p_user_id
      and broker='alpaca' and status='open' and asset_type=v_pos.asset_type
      and case when asset_type='crypto' then regexp_replace(upper(replace(ticker,'/','')),'USD$','')
          else upper(ticker) end =
          case when v_pos.asset_type='crypto' then regexp_replace(upper(replace(v_pos.ticker,'/','')),'USD$','')
          else upper(v_pos.ticker) end)<>1 then
    raise exception 'broker_exit_ownership_ambiguous';
  end if;
  update public.paper_positions set source_payload =
    case when p_pending is null then coalesce(source_payload,'{}'::jsonb)-'broker_exit_pending'
    else jsonb_set(coalesce(source_payload,'{}'::jsonb),'{broker_exit_pending}',p_pending) end
    where id=p_position_id and user_id=p_user_id;
  return jsonb_build_object('ok',true,'claimed',true,'pending',p_pending);
end $$;
revoke all on function public.claim_broker_exit(uuid,uuid,jsonb,jsonb) from public, anon, authenticated;
grant execute on function public.claim_broker_exit(uuid,uuid,jsonb,jsonb) to service_role;

create or replace function public.record_broker_close(
  p_user_id uuid, p_position_id uuid, p_receipt jsonb, p_reason text default 'manual'
) returns jsonb language plpgsql security invoker set search_path = '' as $$
declare
  v_pos public.paper_positions%rowtype;
  v_acct public.paper_accounts%rowtype;
  v_prev public.broker_close_receipts%rowtype;
  v_id text := p_receipt->>'id';
  v_status text := p_receipt->>'status';
  v_qty numeric := (p_receipt->>'filled_qty')::numeric;
  v_avg numeric := (p_receipt->>'filled_avg_price')::numeric;
  v_at timestamptz := (p_receipt->>'filled_at')::timestamptz;
  v_fee numeric := (p_receipt->>'fee_usd')::numeric;
  v_dq numeric; v_dn numeric; v_df numeric; v_price numeric;
  v_entry_fee numeric; v_pnl numeric; v_remaining numeric; v_multiplier numeric;
  v_slice uuid; v_outcome uuid; v_payload jsonb; v_close_status text;
  v_prior boolean; v_terminal boolean; v_entry_confirmed boolean;
  v_entry_fees_known boolean; v_provisional boolean; v_other_claim boolean;
begin
  if coalesce(v_id,'')='' or v_qty is null or v_avg is null
     or v_qty <= 0 or v_avg <= 0 or v_at is null
     or v_qty::text in ('NaN','Infinity','-Infinity')
     or v_avg::text in ('NaN','Infinity','-Infinity')
     or (v_fee is not null and (v_fee < 0 or v_fee::text in ('NaN','Infinity','-Infinity')))
     or v_status is null or v_status not in
       ('filled','partially_filled','canceled','expired','rejected','done_for_day') then
    raise exception 'broker_receipt_invalid_or_unfilled';
  end if;
  -- done_for_day can resume on the next session; it does not release a claim.
  v_terminal := v_status in ('filled','canceled','expired','rejected');
  if v_qty<>round(v_qty,12) or v_qty>=1e18 then
    raise exception 'broker_receipt_quantity_precision';
  end if;
  -- Every writer takes the book lock first, then position, then order receipt.
  -- Position, outcomes, dedupe and counters either all commit or all roll back.
  select * into v_acct from public.paper_accounts where user_id=p_user_id for update;
  if not found then raise exception 'broker_book_missing'; end if;
  if to_regclass('public.option_close_receipts') is not null then
    execute 'select exists(select 1 from public.option_close_receipts where user_id=$1 and broker=$2 and order_id=$3)'
      into v_other_claim using p_user_id,'alpaca',v_id;
    if v_other_claim then raise exception 'broker_receipt_already_claimed_by_options'; end if;
  end if;
  select * into v_pos from public.paper_positions
    where id=p_position_id and user_id=p_user_id for update;
  if not found or v_pos.broker is distinct from 'alpaca' then
    raise exception 'broker_position_mismatch';
  end if;
  if (upper(replace(p_receipt->>'symbol','/','')) is distinct from
      case when v_pos.asset_type='crypto' then
        case when upper(replace(v_pos.ticker,'/','')) like '%USD' then upper(replace(v_pos.ticker,'/',''))
        else upper(v_pos.ticker)||'USD' end else upper(v_pos.ticker) end
     or p_receipt->>'side' is distinct from
       case when v_pos.side='long' then 'sell' else 'buy' end) then
    raise exception 'broker_receipt_instrument_or_side_mismatch';
  end if;
  if v_at < v_pos.entry_at or v_at > now()+interval '5 minutes' then
    raise exception 'broker_receipt_time_mismatch';
  end if;
  select * into v_prev from public.broker_close_receipts
    where user_id=p_user_id and broker='alpaca' and order_id=v_id for update;
  v_prior := found;
  if v_prior and v_prev.position_id <> p_position_id then
    raise exception 'broker_receipt_already_claimed_by_another_position';
  end if;
  v_entry_confirmed := coalesce((v_pos.source_payload->>'entry_basis_verified')::boolean,false);
  v_entry_fees_known := coalesce((v_pos.source_payload->>'entry_fees_known')::boolean,false);
  v_provisional := not(v_entry_confirmed and v_entry_fees_known and v_fee is not null);
  v_multiplier := case when v_pos.asset_type='option' then 100 else 1 end;
  v_dq := v_qty-coalesce(v_prev.cumulative_qty,0);
  v_dn := v_qty*v_avg*v_multiplier-coalesce(v_prev.cumulative_notional,0);
  v_df := case when v_fee is null then 0
    else round(v_fee,4)-round(coalesce(v_prev.cumulative_fee_usd,0),4) end;
  if v_dq < 0 or v_dn < 0 or v_df < 0
     or (v_fee is not null and v_fee<coalesce(v_prev.cumulative_fee_usd,0)) then
    raise exception 'broker_receipt_regressed';
  end if;
  if v_dq=0 and v_dn<>0 then
    raise exception 'broker_fill_revision_requires_review';
  end if;
  if v_dq=0 and v_df=0 then
    -- The final poll may carry the same fills but now a terminal status.
    if v_terminal and v_pos.source_payload#>>'{broker_exit_pending,order_id}'=v_id then
      update public.paper_positions set source_payload=source_payload-'broker_exit_pending'
        where id=p_position_id and user_id=p_user_id;
    end if;
    update public.broker_close_receipts set cumulative_fee_usd=coalesce(v_fee,cumulative_fee_usd),
      receipt=p_receipt,updated_at=now()
      where user_id=p_user_id and broker='alpaca' and order_id=v_id;
    if v_fee is not null then
      update public.paper_positions set source_payload=jsonb_set(jsonb_set(source_payload,
        '{broker_accounting,exit_fees_known}','true'),'{broker_accounting,pnl_provisional}',to_jsonb(v_provisional))
        where id=v_prev.last_slice_id and user_id=p_user_id;
      update public.trade_outcomes set entry_payload=jsonb_set(jsonb_set(entry_payload,
        '{broker_accounting,exit_fees_known}','true'),'{broker_accounting,pnl_provisional}',to_jsonb(v_provisional))
        where id=v_prev.last_outcome_id and user_id=p_user_id;
    end if;
    return jsonb_build_object('ok',true,'duplicate',true,'fill_price',v_avg,
      'realized_pnl_usd',0,'remaining_qty',case when v_pos.status='open' then v_pos.quantity else 0 end,
      'fees_complete',v_entry_fees_known and v_fee is not null,
      'pnl_provisional',v_provisional,'pending',not v_terminal);
  end if;
  if v_dq>0 and (v_pos.status<>'open' or v_dq>v_pos.quantity) then
    raise exception 'broker_fill_exceeds_open_quantity';
  end if;
  -- A late known cumulative fee amends the most recent slice once. The
  -- evidence stays attached to the same fill period; no fake fill is created.
  if v_dq=0 then
    if not v_prior or v_prev.last_slice_id is null then raise exception 'broker_fee_without_fill'; end if;
    update public.paper_positions set fees_usd=fees_usd+v_df,
      realized_pnl_usd=realized_pnl_usd-v_df,
      source_payload=jsonb_set(jsonb_set(coalesce(source_payload,'{}'::jsonb),
        '{broker_accounting,exit_fees_known}','true'),'{broker_accounting,pnl_provisional}',to_jsonb(v_provisional))
      where id=v_prev.last_slice_id and user_id=p_user_id;
    update public.trade_outcomes set realized_pnl_usd=realized_pnl_usd-v_df,
      entry_payload=jsonb_set(jsonb_set(entry_payload,'{broker_accounting,exit_fees_known}','true'),
        '{broker_accounting,pnl_provisional}',to_jsonb(v_provisional))
      where id=v_prev.last_outcome_id and user_id=p_user_id;
    v_pnl := -v_df; v_at := v_prev.filled_at;
    v_slice := v_prev.last_slice_id; v_outcome := v_prev.last_outcome_id;
    v_remaining := case when v_pos.status='open' then v_pos.quantity else 0 end;
    v_price := v_avg;
  else
    v_price := v_dn/v_dq/v_multiplier;
    if v_price<=0 then raise exception 'broker_delta_price_invalid'; end if;
    v_entry_fee := round(coalesce(v_pos.fees_usd,0)*v_dq/v_pos.quantity,4);
    v_pnl := round((case when v_pos.side='long' then 1 else -1 end)*
      (v_dn-v_dq*v_pos.entry_price*v_multiplier)-v_entry_fee-v_df,4);
    v_remaining := v_pos.quantity-v_dq;
    v_payload := coalesce(v_pos.source_payload,'{}'::jsonb)||jsonb_build_object(
      'broker_accounting',jsonb_build_object('exit_order_id',v_id,'exit_fill_verified',true,
        'entry_basis_verified',v_entry_confirmed,'entry_fees_known',v_entry_fees_known,
        'exit_fees_known',v_fee is not null,'pnl_provisional',v_provisional,
        'cash_source','broker_snapshot','parent_position_id',p_position_id));
    if v_terminal and v_payload#>>'{broker_exit_pending,order_id}'=v_id then
      v_payload := v_payload-'broker_exit_pending';
    end if;
    v_close_status := case when v_remaining>0 then 'closed_partial'
      when p_reason in ('stop','target','time','eod') then 'closed_'||p_reason else 'closed_manual' end;
    if v_remaining>0 then
      insert into public.paper_positions(user_id,ticker,asset_type,side,quantity,entry_price,
        entry_at,stop_price,target_price,status,exit_price,exit_at,realized_pnl_usd,fees_usd,
        strategy,source_payload,broker)
      values(p_user_id,v_pos.ticker,v_pos.asset_type,v_pos.side,v_dq,v_pos.entry_price,
        v_pos.entry_at,v_pos.stop_price,v_pos.target_price,v_close_status,v_price,v_at,
        v_pnl,v_entry_fee+v_df,v_pos.strategy,v_payload,'alpaca') returning id into v_slice;
      update public.paper_positions set quantity=v_remaining,fees_usd=fees_usd-v_entry_fee,
        source_payload=case when v_terminal and source_payload#>>'{broker_exit_pending,order_id}'=v_id
          then source_payload-'broker_exit_pending' else source_payload end
        where id=p_position_id and user_id=p_user_id;
    else
      v_slice := p_position_id;
      update public.paper_positions set status=v_close_status,exit_price=v_price,exit_at=v_at,
        realized_pnl_usd=v_pnl,fees_usd=v_entry_fee+v_df,source_payload=v_payload
        where id=p_position_id and user_id=p_user_id;
    end if;
    insert into public.trade_outcomes(user_id,position_id,source_table,ticker,asset_type,
      side,strategy,direction,entry_payload,exit_reason,status,entry_price,exit_price,
      quantity,realized_pnl_usd,opened_at,closed_at)
    -- Keep the original parent linkage used by restart-safe profit-step
    -- counting. Receipt.last_slice_id identifies the actual closed child.
    values(p_user_id,p_position_id,'paper_positions',v_pos.ticker,v_pos.asset_type,v_pos.side,
      v_pos.strategy,v_pos.source_payload->>'direction',v_payload||jsonb_build_object('closed_slice_id',v_slice),p_reason,v_close_status,
      v_pos.entry_price,v_price,v_dq,v_pnl,v_pos.entry_at,v_at) returning id into v_outcome;
  end if;
  -- Period counters follow their persisted reset dates, never the host timezone.
  -- Do not add sale proceeds to broker-synchronized cash a second time.
  update public.paper_accounts set
    ytd_realized_pnl_usd=ytd_realized_pnl_usd+v_pnl,
    today_realized_pnl_usd=today_realized_pnl_usd+case
      when (v_at at time zone 'UTC')::date=last_reset_date then v_pnl else 0 end,
    week_realized_pnl_usd=coalesce(week_realized_pnl_usd,0)+case
      when (v_at at time zone 'UTC')::date>=week_start_date
       and (v_at at time zone 'UTC')::date<week_start_date+7 then v_pnl else 0 end,
    consecutive_losses=case when v_dq>0 and v_remaining=0 then
      case when (select coalesce(sum(realized_pnl_usd),0) from public.trade_outcomes
        where user_id=p_user_id and source_table='paper_positions' and position_id=p_position_id)<0
        then coalesce(consecutive_losses,0)+1 else 0 end
      else consecutive_losses end,updated_at=now()
    where user_id=p_user_id;
  insert into public.broker_close_receipts(user_id,broker,order_id,position_id,
    cumulative_qty,cumulative_notional,cumulative_fee_usd,last_slice_id,last_outcome_id,
    filled_at,receipt)
  values(p_user_id,'alpaca',v_id,p_position_id,v_qty,v_qty*v_avg*v_multiplier,
    coalesce(v_fee,v_prev.cumulative_fee_usd),v_slice,v_outcome,v_at,p_receipt)
  on conflict(user_id,broker,order_id) do update set
    cumulative_qty=excluded.cumulative_qty,cumulative_notional=excluded.cumulative_notional,
    cumulative_fee_usd=excluded.cumulative_fee_usd,last_slice_id=excluded.last_slice_id,
    last_outcome_id=excluded.last_outcome_id,filled_at=excluded.filled_at,
    receipt=excluded.receipt,updated_at=now();
  return jsonb_build_object('ok',true,'duplicate',false,'fill_price',v_price,
    'realized_pnl_usd',v_pnl,'remaining_qty',v_remaining,'fees_complete',coalesce(v_entry_fees_known,false) and v_fee is not null,
    'pending',not v_terminal,'slice_id',v_slice,'pnl_provisional',coalesce(v_provisional,true));
end $$;
revoke all on function public.record_broker_close(uuid,uuid,jsonb,text) from public, anon, authenticated;
grant execute on function public.record_broker_close(uuid,uuid,jsonb,text) to service_role;
insert into public.schema_migrations(version,assumed,notes)
values('20260918155909_broker_close_receipts.sql',false,'Transactional broker receipt accounting; no historical recomputation')
on conflict(version) do nothing;
commit;
