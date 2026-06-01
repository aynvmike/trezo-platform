-- =====================================================================
-- Trezo — ISO 20022 payments foundation
-- =====================================================================
-- ISO 20022 is the global payments messaging standard now adopted by
-- Fedwire (Mar 2025), SWIFT MX (Nov 2025 cutover), FedNow, RTP, CHAPS,
-- T2, SEPA Inst, and most domestic rails. When Trezo eventually wires
-- real money movement (KINDRIP bank pulls, vault deposits/withdrawals,
-- broker funding, profit withdrawals), the canonical record needs to
-- be ISO 20022-shaped so we can render pain.001 / pacs.008 / camt.053
-- messages without re-modelling at the integration point.
--
-- The shape below maps to the pain.001 (CustomerCreditTransferInitiation)
-- and pacs.008 (FIToFICustomerCreditTransfer) field set. We store the
-- canonical instruction here; the adapter renders the XML on demand
-- when we hand it to a bank or PSP.
--
-- Today nothing in Trezo actually moves real money - this table sits
-- ready. KINDRIP and vault flows can start writing rows now so the
-- audit trail builds up before the first real wire.
-- =====================================================================

create table if not exists public.payment_instructions (
  id                              uuid primary key default gen_random_uuid(),
  user_id                         uuid not null references auth.users(id) on delete cascade,

  -- ISO 20022 message envelope
  message_id                      text not null,                              -- pain.001 / pacs.008 <MsgId>
  end_to_end_id                   text not null,                              -- <EndToEndId> - travels through the chain
  instruction_id                  text,                                       -- <InstrId> - per-instruction reference
  uetr                            uuid default gen_random_uuid(),             -- Unique End-to-end Transaction Reference (SWIFT GPI)

  -- Lifecycle - draft -> queued -> submitted -> accepted/rejected -> settled
  status                          text not null default 'draft'
    check (status in ('draft', 'queued', 'submitted', 'accepted', 'rejected', 'settled', 'returned', 'cancelled')),
  status_reason                   text,                                       -- ISO 20022 status reason code if rejected
  status_reason_description       text,

  -- Trezo-side classification
  flow                            text not null
    check (flow in ('kindrip_contribution', 'vault_deposit', 'vault_withdrawal', 'broker_funding', 'profit_withdrawal', 'manual')),

  -- Payment amount (ISO 20022 InstrumentedAmount)
  amount_value                    numeric(18, 5) not null check (amount_value > 0),
  amount_currency                 text not null check (char_length(amount_currency) = 3),  -- ISO 4217

  -- Requested execution date / settlement date
  requested_execution_date        date not null,
  settlement_date                 date,

  -- Debtor (the payer) - ISO 20022 <Dbtr>
  debtor_name                     text not null,
  debtor_account_id               text not null,             -- IBAN, account number, or routing+account composite
  debtor_account_type             text default 'OTHR',       -- IBAN, BBAN, OTHR
  debtor_agent_bic                text,                      -- <DbtrAgt>/<FinInstnId>/<BICFI>
  debtor_agent_clearing_system    text,                      -- USABA (Fedwire), CHAPS, etc.
  debtor_agent_clearing_id        text,                      -- routing number / sort code
  debtor_country                  text,                      -- ISO 3166-1 alpha-2

  -- Creditor (the payee) - ISO 20022 <Cdtr>
  creditor_name                   text not null,
  creditor_account_id             text not null,
  creditor_account_type           text default 'OTHR',
  creditor_agent_bic              text,
  creditor_agent_clearing_system  text,
  creditor_agent_clearing_id      text,
  creditor_country                text,

  -- Payment metadata
  -- ISO 20022 PaymentMethod: TRF=credit transfer, CHK=cheque, DD=direct debit
  payment_method                  text not null default 'TRF'
    check (payment_method in ('TRF', 'CHK', 'DD', 'TRA')),
  -- ServiceLevel: INST=instant, NURG=non-urgent, URGP=urgent, SEPA, etc.
  service_level                   text default 'NURG',
  -- LocalInstrument: rail-specific (FedNow=FNW, RTP=RTP, CHAPS=CHAPS)
  local_instrument                text,
  category_purpose                text,                      -- INTC, CASH, SALA, etc.
  purpose_code                    text,                      -- granular purpose
  remittance_info_unstructured    text,                      -- free-text reference
  remittance_info_structured      jsonb,                     -- creditor reference / structured remit

  -- Rendered XML cache (regenerate on update)
  rendered_pain001_xml            text,
  rendered_pacs008_xml            text,
  rendered_at                     timestamptz,

  -- References back into Trezo
  related_table                   text,
  related_id                      uuid,

  created_at                      timestamptz not null default now(),
  updated_at                      timestamptz not null default now(),

  unique (user_id, end_to_end_id)
);

create index if not exists payment_instructions_user_idx
  on public.payment_instructions(user_id, created_at desc);

create index if not exists payment_instructions_status_idx
  on public.payment_instructions(status, requested_execution_date);

create index if not exists payment_instructions_flow_idx
  on public.payment_instructions(user_id, flow, created_at desc);

drop trigger if exists payment_instructions_set_updated_at on public.payment_instructions;
create trigger payment_instructions_set_updated_at
  before update on public.payment_instructions
  for each row execute function public.set_updated_at();

alter table public.payment_instructions enable row level security;

drop policy if exists payment_instructions_self_all on public.payment_instructions;
create policy payment_instructions_self_all on public.payment_instructions
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

comment on table public.payment_instructions is
  'ISO 20022-shaped canonical record for every Trezo money movement. The adapter renders pain.001 / pacs.008 XML on demand. Today nothing actually wires - the table sits ready for FedNow / RTP / SWIFT MX integration.';
comment on column public.payment_instructions.uetr is
  'Unique End-to-end Transaction Reference (UUID4). SWIFT GPI standard; the same UETR travels with the payment through every intermediary, used for tracking.';
comment on column public.payment_instructions.end_to_end_id is
  'pain.001 <EndToEndId> - up to 35 chars, opaque to intermediaries, preserved end-to-end. We mirror it from Trezo internal IDs so we can correlate the wire with the originating Trezo action.';
