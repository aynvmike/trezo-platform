-- 0024_agent_memory.sql
-- Phase 13 — agent shared & evolving memory.
-- Agents pass transient messages on the bus; this table gives them
-- something durable. Memory in the 'shared' scope is readable by every
-- agent, so insights cross-pollinate and accumulate across restarts.

create table if not exists public.agent_memory (
  id uuid primary key default gen_random_uuid(),
  agent text not null,                    -- which agent wrote it
  scope text not null default 'shared',   -- 'shared' = all agents; else the owning agent
  topic text not null,                    -- dedup / upsert key within (agent, scope)
  category text not null default 'insight', -- insight | observation | metric | warning
  content text not null,                  -- the plain-language memory
  weight numeric not null default 1,      -- reinforcement — bumps when re-remembered
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (agent, scope, topic)
);

create index if not exists agent_memory_scope_idx
  on public.agent_memory (scope, weight desc, updated_at desc);

alter table public.agent_memory enable row level security;

-- System/global knowledge: any signed-in user may read it (the dashboard
-- shows it); only the service-role agents write. Service role bypasses RLS.
create policy "agent_memory_select_auth" on public.agent_memory
  for select using (auth.role() = 'authenticated');

comment on table public.agent_memory is
  'Persistent, evolving, shared memory for the Trezo agents (Phase 13).';
