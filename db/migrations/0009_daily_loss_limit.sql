-- =====================================================================
-- Trezo — Phase 6a.1: Daily loss limit + profile editability
-- =====================================================================

-- Add a per-user daily loss cap. 0 = disabled (no enforcement).
alter table public.profiles
  add column if not exists daily_loss_limit_usd numeric(14, 2) not null default 0
    check (daily_loss_limit_usd >= 0);
