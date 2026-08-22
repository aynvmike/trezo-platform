-- 0057 — Dividends (Long-Term) lane: the market-wide screen cache.
--
-- Why a table and not just a process cache: the §4 entry screen is what
-- turns a market-wide POOL into a market-wide SCREEN, and it only does
-- that if knowledge ACCUMULATES. A process-lifetime cache resets on every
-- restart and the lane goes back to re-screening the same handful of
-- names inside its rate budget forever. Persisted, each name screened
-- once is free for a week, and coverage ratchets toward the whole market.
--
-- `payload` holds the full ScreenResult including the per-rule checks
-- dict, so the UI can show WHY a name failed — and can distinguish
-- "failed the screen" from "we could not verify it", which are very
-- different facts and must never be collapsed into one red X.

create table if not exists public.dividend_screen_cache (
    ticker        text primary key,
    tier          text not null default 'UNVERIFIED',
    passed        boolean not null default false,
    payload       jsonb not null default '{}'::jsonb,
    screened_at   timestamptz not null default now()
);

-- The Wheel asks "what passed, by tier" every universe build.
create index if not exists dividend_screen_cache_tier_idx
    on public.dividend_screen_cache (tier, passed);

-- Staleness sweeps: find rows older than the 7-day TTL.
create index if not exists dividend_screen_cache_screened_at_idx
    on public.dividend_screen_cache (screened_at desc);

comment on table public.dividend_screen_cache is
    'Market-wide dividend entry-screen results (spec DIVIDEND_LT §4). '
    'tier: GROWTH | HIGH_YIELD | FAIL | UNVERIFIED. UNVERIFIED means we '
    'lacked data, NOT that the name failed — it is never eligible on '
    'optimism. TTL 7 days, refreshed lazily on read.';

alter table public.dividend_screen_cache enable row level security;

-- Service-role only: this is engine-owned reference data, not user data.
drop policy if exists dividend_screen_cache_service on public.dividend_screen_cache;
create policy dividend_screen_cache_service
    on public.dividend_screen_cache
    for all
    using (auth.role() = 'service_role')
    with check (auth.role() = 'service_role');
