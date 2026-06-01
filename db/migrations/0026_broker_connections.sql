-- =====================================================================
-- Trezo — Phase 10c: Per-user broker connections (OAuth)
-- =====================================================================
-- Tokens are stored encrypted, one row per (user_id, broker). A user
-- can be connected to many brokers; each broker integration uses the
-- generic shape below.
--
-- Encryption is done in the web layer using TREZO_TOKENS_KEY (AES-256-
-- GCM). The DB stores opaque ciphertext + nonce; nothing in Postgres
-- can decrypt these. Rotation = re-encrypt + write.
-- =====================================================================

create table if not exists public.broker_connections (
  id                   uuid primary key default gen_random_uuid(),
  user_id              uuid not null references auth.users(id) on delete cascade,
  broker               text not null,                 -- 'alpaca' | 'alpaca-live' | 'ibkr' | ...
  account_id           text,                          -- the broker's own account id
  -- Encrypted access + refresh tokens. nonce stored with the ciphertext
  -- (web layer formats them as base64(nonce):base64(ciphertext+tag)).
  access_token_enc     text not null,
  refresh_token_enc    text,
  expires_at           timestamptz,                   -- nullable (some brokers issue non-expiring tokens)
  scopes               text,                          -- whitespace-joined oauth scopes
  status               text not null default 'active' check (status in ('active', 'expired', 'revoked')),
  connected_at         timestamptz not null default now(),
  updated_at           timestamptz not null default now(),
  unique (user_id, broker)
);

drop trigger if exists broker_connections_set_updated_at on public.broker_connections;
create trigger broker_connections_set_updated_at
  before update on public.broker_connections
  for each row execute function public.set_updated_at();

create index if not exists broker_connections_user_idx
  on public.broker_connections(user_id, broker);

alter table public.broker_connections enable row level security;

drop policy if exists broker_connections_self_all on public.broker_connections;
create policy broker_connections_self_all on public.broker_connections
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

comment on table public.broker_connections is
  'Per-user OAuth connections to brokers (Alpaca, IBKR, etc.). Tokens are encrypted in the web layer with TREZO_TOKENS_KEY; the DB never sees plaintext.';
