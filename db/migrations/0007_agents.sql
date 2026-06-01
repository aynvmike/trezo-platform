-- =====================================================================
-- Trezo — Phase 5: Agent runtime
-- =====================================================================

-- ---------------------------------------------------------------------
-- agent_state — per-user enable/disable + last-tick timestamp per agent
-- ---------------------------------------------------------------------
create table if not exists public.agent_state (
  user_id      uuid not null references auth.users(id) on delete cascade,
  agent_name   text not null,
  enabled      boolean not null default true,
  last_tick_at timestamptz,
  tick_count   integer not null default 0,
  message_count integer not null default 0,
  updated_at   timestamptz not null default now(),
  primary key (user_id, agent_name)
);

drop trigger if exists agent_state_set_updated_at on public.agent_state;
create trigger agent_state_set_updated_at
  before update on public.agent_state
  for each row execute function public.set_updated_at();

alter table public.agent_state enable row level security;

drop policy if exists agent_state_self_all on public.agent_state;
create policy agent_state_self_all on public.agent_state
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- ---------------------------------------------------------------------
-- agent_messages — structured message log (richer than agent_logs)
-- ---------------------------------------------------------------------
create table if not exists public.agent_messages (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid references auth.users(id) on delete cascade,
  agent_name   text not null,
  kind         text not null,           -- 'signal', 'veto', 'approve', 'execute', 'alert', 'info', 'error'
  confidence   numeric(4, 3) check (confidence between 0 and 1),
  payload      jsonb not null default '{}'::jsonb,
  ref_id       uuid,                    -- optional pointer to related message (e.g. veto -> signal)
  created_at   timestamptz not null default now()
);

create index if not exists agent_messages_user_idx on public.agent_messages(user_id, created_at desc);
create index if not exists agent_messages_agent_idx on public.agent_messages(agent_name, created_at desc);
create index if not exists agent_messages_kind_idx on public.agent_messages(kind, created_at desc);

alter table public.agent_messages enable row level security;

drop policy if exists agent_messages_self_select on public.agent_messages;
create policy agent_messages_self_select on public.agent_messages
  for select using (auth.uid() = user_id);

drop policy if exists agent_messages_self_insert on public.agent_messages;
create policy agent_messages_self_insert on public.agent_messages
  for insert with check (auth.uid() = user_id);
-- service role bypasses RLS for the agents background writer
