-- Independent paper-book capability settings and scope ownership.
-- Enabling an existing book is a separate owner-scoped operation in ops/enable_books.py.
begin;
alter table public.bot_settings
  add column if not exists day_options_enabled boolean not null default false,
  add column if not exists spreads_enabled boolean not null default false,
  add column if not exists long_options_enabled boolean not null default false,
  add column if not exists dividend_lt_enabled boolean not null default false,
  add column if not exists reevaluation_enabled boolean not null default false,
  add column if not exists crypto_reevaluation_enabled boolean not null default false;
alter table public.strategy_scope_adjustments
  add column if not exists user_id uuid references public.trading_accounts(account_key) on delete cascade;
create index if not exists scope_adjustments_book_created_idx
  on public.strategy_scope_adjustments(user_id, created_at desc);
alter table public.strategy_scope_adjustments enable row level security;
revoke all on public.strategy_scope_adjustments from anon;
grant select, update on public.strategy_scope_adjustments to authenticated;
drop policy if exists scope_adjustments_read on public.strategy_scope_adjustments;
drop policy if exists scope_adjustments_update on public.strategy_scope_adjustments;
drop policy if exists scope_adjustments_book_read on public.strategy_scope_adjustments;
drop policy if exists scope_adjustments_book_update on public.strategy_scope_adjustments;
create policy scope_adjustments_book_read on public.strategy_scope_adjustments
  for select to authenticated
  using (user_id in (select public.my_account_keys()));
create policy scope_adjustments_book_update on public.strategy_scope_adjustments
  for update to authenticated
  using (user_id in (select public.my_account_keys()))
  with check (user_id in (select public.my_account_keys()));
-- Existing null-book adjustments remain historical records; the engine
-- never imports their controls into any book after this migration.
commit;
