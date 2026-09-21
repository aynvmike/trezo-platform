-- Supabase CLI-generated migration; NOT APPLIED remotely.
-- Requires 20260918155909_broker_close_receipts.sql. No history is rewritten.
begin;

alter table public.options_positions
  add column if not exists broker_exit_pending jsonb,
  add column if not exists broker_accounting jsonb;

create table if not exists public.option_close_receipts (
  user_id uuid not null references public.trading_accounts(account_key),
  broker text not null check (broker='alpaca'),
  order_id text not null,
  position_id uuid not null references public.options_positions(id),
  cumulative_qty integer not null,
  cumulative_notional numeric not null,
  cumulative_fee_usd numeric,
  fee_covered_qty integer,
  last_slice_id uuid references public.options_positions(id),
  last_outcome_id uuid,
  filled_at timestamptz not null,
  receipt jsonb not null,
  updated_at timestamptz not null default now(),
  primary key(user_id,broker,order_id)
);
alter table public.option_close_receipts enable row level security;
revoke all on public.option_close_receipts from public, anon, authenticated;
grant select,insert,update on public.option_close_receipts to service_role;

create or replace function public.claim_option_broker_exit(
  p_user_id uuid,p_position_id uuid,p_expected_pending jsonb,p_pending jsonb
) returns jsonb language plpgsql security invoker set search_path='' as $$
declare
  v_pos public.options_positions%rowtype;
  v_occ text; v_side text; v_qty numeric;
begin
  perform 1 from public.paper_accounts where user_id=p_user_id for update;
  if not found then raise exception 'broker_book_missing'; end if;
  select * into v_pos from public.options_positions
    where id=p_position_id and user_id=p_user_id for update;
  if not found or v_pos.status<>'open' then raise exception 'option_position_not_open'; end if;
  if v_pos.broker_exit_pending is distinct from p_expected_pending then
    return jsonb_build_object('ok',true,'claimed',false,'pending',v_pos.broker_exit_pending);
  end if;
  if p_pending is not null then
    if v_pos.option_type not in ('call','put') or v_pos.option_type is null
       or v_pos.expiration is null or v_pos.strike is null or v_pos.strike<=0
       or v_pos.strike*1000<>trunc(v_pos.strike*1000) or v_pos.strike>=100000
       or v_pos.net_premium_usd=0 or v_pos.net_premium_usd::text in ('NaN','Infinity','-Infinity')
       or jsonb_typeof(v_pos.legs)<>'array' or jsonb_array_length(v_pos.legs)>1 then
      raise exception 'option_exit_instrument_ambiguous';
    end if;
    v_occ := upper(v_pos.underlying)||to_char(v_pos.expiration,'YYMMDD')||
      case when v_pos.option_type='call' then 'C' else 'P' end||lpad((v_pos.strike*1000)::bigint::text,8,'0');
    v_side := case when v_pos.net_premium_usd<0 then 'sell' else 'buy' end;
    v_qty := (p_pending->>'quantity')::numeric;
    if jsonb_typeof(p_pending)<>'object' or coalesce(p_pending->>'intent_id','')=''
       or coalesce(p_pending->>'started_at','')='' or p_pending->>'symbol' is distinct from v_occ
       or p_pending->>'side' is distinct from v_side or v_qty is null or v_qty<=0
       or v_qty<>trunc(v_qty) or v_qty>v_pos.contracts then
      raise exception 'option_exit_intent_invalid';
    end if;
    if (p_pending->>'started_at')::timestamptz<v_pos.opened_at
       or (p_pending->>'started_at')::timestamptz>now()+interval '5 minutes' then
      raise exception 'option_exit_intent_time_invalid';
    end if;
    if p_expected_pending is null and (
      (select count(*) from public.options_positions where user_id=p_user_id and status='open'
        and upper(underlying)=upper(v_pos.underlying) and option_type=v_pos.option_type
        and strike=v_pos.strike and expiration=v_pos.expiration)<>1
      or exists(select 1 from public.paper_positions where user_id=p_user_id and status='open'
        and broker='alpaca' and asset_type='option' and upper(ticker)=v_occ)) then
      raise exception 'option_exit_ownership_ambiguous';
    end if;
    if p_expected_pending is not null and
       (p_expected_pending-'order_id') is distinct from (p_pending-'order_id') then
      raise exception 'option_exit_intent_changed';
    end if;
    if p_expected_pending->>'order_id' is not null and
       p_expected_pending->>'order_id' is distinct from p_pending->>'order_id' then
      raise exception 'option_exit_order_changed';
    end if;
  end if;
  update public.options_positions set broker_exit_pending=p_pending where id=p_position_id and user_id=p_user_id;
  return jsonb_build_object('ok',true,'claimed',true,'pending',p_pending);
end $$;
revoke all on function public.claim_option_broker_exit(uuid,uuid,jsonb,jsonb) from public,anon,authenticated;
grant execute on function public.claim_option_broker_exit(uuid,uuid,jsonb,jsonb) to service_role;

create or replace function public.record_option_broker_close(
  p_user_id uuid,p_position_id uuid,p_receipt jsonb,p_reason text default 'manual'
) returns jsonb language plpgsql security invoker set search_path='' as $$
declare
  v_pos public.options_positions%rowtype;
  v_prev public.option_close_receipts%rowtype;
  v_id text := p_receipt->>'id';
  v_status text := p_receipt->>'status';
  v_qty numeric := (p_receipt->>'filled_qty')::numeric;
  v_avg numeric := (p_receipt->>'filled_avg_price')::numeric;
  v_fee numeric := (p_receipt->>'fee_usd')::numeric;
  v_at timestamptz := (p_receipt->>'filled_at')::timestamptz;
  v_occ text; v_side text; v_prior boolean; v_terminal boolean;
  v_dq integer; v_dn numeric; v_df numeric; v_price numeric;
  v_premium numeric; v_entry_fee numeric; v_remaining_fee numeric;
  v_pnl numeric; v_remaining integer; v_slice uuid; v_outcome uuid;
  v_meta jsonb; v_remaining_meta jsonb; v_provisional boolean;
  v_entry_verified boolean; v_entry_fees_known boolean; v_exit_fees_known boolean;
begin
  if coalesce(v_id,'')='' or v_qty is null or v_avg is null or v_at is null
     or v_qty<=0 or v_qty<>trunc(v_qty) or v_qty>2147483647 or v_avg<=0
     or v_qty::text in ('NaN','Infinity','-Infinity') or v_avg::text in ('NaN','Infinity','-Infinity')
     or (v_fee is not null and (v_fee<0 or v_fee::text in ('NaN','Infinity','-Infinity')))
     or v_status is null or v_status not in ('filled','partially_filled','canceled','expired','rejected','done_for_day') then
    raise exception 'option_receipt_invalid_or_unfilled';
  end if;
  v_terminal := v_status in ('filled','canceled','expired','rejected');
  -- All receipt writers lock book first, then source position, then receipt.
  perform 1 from public.paper_accounts where user_id=p_user_id for update;
  if not found then raise exception 'broker_book_missing'; end if;
  select * into v_pos from public.options_positions where id=p_position_id and user_id=p_user_id for update;
  if not found then raise exception 'option_position_mismatch'; end if;
  if v_pos.option_type not in ('call','put') or v_pos.option_type is null
     or v_pos.expiration is null or v_pos.strike is null or v_pos.strike<=0
     or v_pos.strike*1000<>trunc(v_pos.strike*1000) or v_pos.strike>=100000
     or v_pos.net_premium_usd=0 or v_pos.net_premium_usd::text in ('NaN','Infinity','-Infinity')
     or jsonb_typeof(v_pos.legs)<>'array' or jsonb_array_length(v_pos.legs)>1 then
    raise exception 'option_exit_instrument_ambiguous';
  end if;
  v_occ := upper(v_pos.underlying)||to_char(v_pos.expiration,'YYMMDD')||
    case when v_pos.option_type='call' then 'C' else 'P' end||lpad((v_pos.strike*1000)::bigint::text,8,'0');
  v_side := case when v_pos.net_premium_usd<0 then 'sell' else 'buy' end;
  if p_receipt->>'symbol' is distinct from v_occ or p_receipt->>'side' is distinct from v_side then
    raise exception 'option_receipt_instrument_or_side_mismatch';
  end if;
  if v_at<v_pos.opened_at or v_at>now()+interval '5 minutes' then
    raise exception 'option_receipt_time_mismatch';
  end if;
  if v_pos.broker_exit_pending is not null and (
       v_pos.broker_exit_pending->>'order_id' is distinct from v_id
       or v_qty>(v_pos.broker_exit_pending->>'quantity')::numeric) then
    raise exception 'option_receipt_pending_mismatch';
  end if;
  if exists(select 1 from public.broker_close_receipts where user_id=p_user_id and broker='alpaca' and order_id=v_id) then
    raise exception 'option_receipt_claimed_by_paper_ledger';
  end if;
  select * into v_prev from public.option_close_receipts
    where user_id=p_user_id and broker='alpaca' and order_id=v_id for update;
  v_prior := found;
  if v_prior and v_prev.position_id<>p_position_id then raise exception 'option_receipt_already_claimed'; end if;
  if not v_prior and v_pos.broker_exit_pending is null and
     (v_status<>'filled' or v_qty<>v_pos.contracts) then
    raise exception 'option_partial_receipt_requires_intent';
  end if;
  if not v_prior and (exists(select 1 from public.options_positions where user_id=p_user_id and status='open'
        and id<>p_position_id and upper(underlying)=upper(v_pos.underlying) and option_type=v_pos.option_type
        and strike=v_pos.strike and expiration=v_pos.expiration)
      or exists(select 1 from public.paper_positions where user_id=p_user_id and status='open'
        and broker='alpaca' and asset_type='option' and upper(ticker)=v_occ)) then
    raise exception 'option_exit_ownership_ambiguous';
  end if;
  v_entry_verified := coalesce((v_pos.broker_accounting->>'entry_basis_verified')::boolean,false);
  v_entry_fees_known := coalesce((v_pos.broker_accounting->>'entry_fees_known')::boolean,false)
    and v_pos.broker_accounting->>'entry_fee_usd' is not null;
  v_remaining_fee := case when v_entry_fees_known then (v_pos.broker_accounting->>'entry_fee_usd')::numeric else 0 end;
  if v_remaining_fee<0 or v_remaining_fee::text in ('NaN','Infinity','-Infinity') then
    raise exception 'option_entry_fee_invalid';
  end if;
  v_dq := v_qty::integer-coalesce(v_prev.cumulative_qty,0);
  -- A known fee on an earlier partial fill says nothing about later fills.
  v_exit_fees_known := v_fee is not null or
    (v_dq=0 and v_prev.cumulative_fee_usd is not null and v_prev.fee_covered_qty=v_qty);
  v_provisional := not(v_entry_verified and v_entry_fees_known and v_exit_fees_known);
  v_dn := v_qty*v_avg*100-coalesce(v_prev.cumulative_notional,0);
  v_df := case when v_fee is null then 0 else v_fee-coalesce(v_prev.cumulative_fee_usd,0) end;
  if v_dq<0 or v_dn<0 or v_df<0 then raise exception 'option_receipt_regressed'; end if;
  if v_dq=0 and v_dn<>0 then raise exception 'option_fill_revision_requires_review'; end if;
  if v_dq>0 and (v_pos.status<>'open' or v_dq>v_pos.contracts) then
    raise exception 'option_fill_exceeds_open_contracts';
  end if;
  v_remaining := case when v_pos.status='open' then v_pos.contracts-v_dq else 0 end;
  if v_dq=0 then
    if not v_prior then raise exception 'option_fee_without_fill'; end if;
    v_slice := v_prev.last_slice_id; v_outcome := v_prev.last_outcome_id;
    v_price := v_avg; v_pnl := -v_df;
    update public.options_positions set realized_pnl_usd=realized_pnl_usd-v_df,
      broker_accounting=coalesce(broker_accounting,'{}')||jsonb_build_object(
        'exit_fees_known',v_exit_fees_known,'pnl_provisional',v_provisional)
      where id=v_slice and user_id=p_user_id;
    update public.trade_outcomes set realized_pnl_usd=realized_pnl_usd-v_df,
      entry_payload=jsonb_set(coalesce(entry_payload,'{}'),'{broker_accounting}',
        coalesce(entry_payload->'broker_accounting','{}')||jsonb_build_object(
          'exit_fees_known',v_exit_fees_known,'pnl_provisional',v_provisional))
      where id=v_outcome and user_id=p_user_id;
    v_at := v_prev.filled_at;
  else
    v_price := v_dn/v_dq/100;
    if v_price<=0 then raise exception 'option_delta_price_invalid'; end if;
    v_premium := round(v_pos.net_premium_usd*v_dq/v_pos.contracts,4);
    v_entry_fee := round(v_remaining_fee*v_dq/v_pos.contracts,4);
    v_pnl := round(v_premium+case when v_side='sell' then v_dn else -v_dn end-v_entry_fee-v_df,4);
    v_meta := coalesce(v_pos.broker_accounting,'{}')||jsonb_build_object(
      'exit_order_id',v_id,'exit_fill_verified',true,'exit_fill_price',v_price,
      'exit_reason',p_reason,'entry_basis_verified',v_entry_verified,
      'entry_fees_known',v_entry_fees_known,'entry_fee_usd',case when v_entry_fees_known then v_entry_fee else null end,
      'exit_fees_known',v_exit_fees_known,'pnl_provisional',v_provisional,
      'parent_position_id',p_position_id,'cash_source','broker_snapshot');
    if v_remaining>0 then
      insert into public.options_positions(user_id,underlying,strategy,direction,option_type,
        strike,expiration,contracts,net_premium_usd,modeled_iv,legs,status,realized_pnl_usd,
        opened_at,closed_at,notes,broker_accounting)
      values(p_user_id,v_pos.underlying,v_pos.strategy,v_pos.direction,v_pos.option_type,
        v_pos.strike,v_pos.expiration,v_dq,v_premium,v_pos.modeled_iv,v_pos.legs,'closed_manual',
        v_pnl,v_pos.opened_at,v_at,v_pos.notes,v_meta) returning id into v_slice;
      v_remaining_meta := coalesce(v_pos.broker_accounting,'{}')||jsonb_build_object(
        'entry_fee_usd',case when v_entry_fees_known then v_remaining_fee-v_entry_fee else null end);
      update public.options_positions set contracts=v_remaining,
        net_premium_usd=net_premium_usd-v_premium,broker_accounting=v_remaining_meta
        where id=p_position_id and user_id=p_user_id;
    else
      v_slice := p_position_id;
      update public.options_positions set status='closed_manual',realized_pnl_usd=v_pnl,
        closed_at=v_at,broker_accounting=v_meta where id=p_position_id and user_id=p_user_id;
    end if;
    insert into public.trade_outcomes(user_id,position_id,source_table,ticker,asset_type,side,
      strategy,direction,entry_payload,exit_reason,status,entry_price,exit_price,quantity,
      realized_pnl_usd,opened_at,closed_at)
    values(p_user_id,p_position_id,'options_positions',v_occ,'option',
      case when v_side='sell' then 'long' else 'short' end,v_pos.strategy,v_pos.direction,
      jsonb_build_object('broker_accounting',v_meta,'closed_slice_id',v_slice),p_reason,'closed_manual',
      abs(v_premium)/v_dq/100,v_price,v_dq,v_pnl,v_pos.opened_at,v_at) returning id into v_outcome;
  end if;
  -- A daily pause is not terminal. Keep its durable claim for the next poll.
  if v_terminal and v_pos.broker_exit_pending->>'order_id'=v_id then
    update public.options_positions set broker_exit_pending=null where id=p_position_id and user_id=p_user_id;
  end if;
  -- Never re-add broker sale proceeds to synchronized cash.
  update public.paper_accounts set ytd_realized_pnl_usd=ytd_realized_pnl_usd+v_pnl,
    today_realized_pnl_usd=today_realized_pnl_usd+case when
      (v_at at time zone 'UTC')::date=last_reset_date then v_pnl else 0 end,
    week_realized_pnl_usd=coalesce(week_realized_pnl_usd,0)+case when
      (v_at at time zone 'UTC')::date>=week_start_date and (v_at at time zone 'UTC')::date<week_start_date+7
      then v_pnl else 0 end,updated_at=now() where user_id=p_user_id;
  insert into public.option_close_receipts(user_id,broker,order_id,position_id,cumulative_qty,
    cumulative_notional,cumulative_fee_usd,fee_covered_qty,last_slice_id,last_outcome_id,filled_at,receipt)
  values(p_user_id,'alpaca',v_id,p_position_id,v_qty::integer,v_qty*v_avg*100,
    coalesce(v_fee,v_prev.cumulative_fee_usd),case when v_fee is not null then v_qty::integer else v_prev.fee_covered_qty end,
    v_slice,v_outcome,v_at,p_receipt)
  on conflict(user_id,broker,order_id) do update set cumulative_qty=excluded.cumulative_qty,
    cumulative_notional=excluded.cumulative_notional,cumulative_fee_usd=excluded.cumulative_fee_usd,
    fee_covered_qty=excluded.fee_covered_qty,
    last_slice_id=excluded.last_slice_id,last_outcome_id=excluded.last_outcome_id,
    filled_at=excluded.filled_at,receipt=excluded.receipt,updated_at=now();
  return jsonb_build_object('ok',true,'duplicate',v_dq=0 and v_df=0,'fill_price',v_price,
    'closed_qty',v_dq,'remaining_qty',v_remaining,'realized_pnl_usd',v_pnl,
    'pending',not v_terminal,'pnl_provisional',v_provisional,'slice_id',v_slice);
end $$;
revoke all on function public.record_option_broker_close(uuid,uuid,jsonb,text) from public,anon,authenticated;
grant execute on function public.record_option_broker_close(uuid,uuid,jsonb,text) to service_role;
insert into public.schema_migrations(version,assumed,notes)
values('20260918160730_option_close_receipts',false,'Atomic option broker exit claims and cumulative actual-fill accounting')
on conflict(version) do nothing;
commit;
