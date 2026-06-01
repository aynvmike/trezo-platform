-- =====================================================================
-- Trezo — Phase 9.5: configurable consecutive-loss kill-switch limit
--
-- The Phase 8c kill-switch halted the day after 3 losing trades in a row.
-- That is too tight for aggressive trading, which expects losing streaks.
-- This makes the limit a Bot Tuning dial: conservative ~3, aggressive ~7.
-- =====================================================================

alter table public.bot_settings
  add column if not exists consecutive_loss_limit integer not null default 3
  check (consecutive_loss_limit between 2 and 10);
