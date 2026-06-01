-- 0022_extended_strategy.sql
-- Phase 10c — Layer 4 (Extended Strategy), the multi-day swing layer.
-- Adds the Bot Tuning on/off toggle for the Extended Strategy scanner.

alter table public.bot_settings
  add column if not exists extended_enabled boolean not null default true;

comment on column public.bot_settings.extended_enabled is
  'Layer 4 Extended Strategy (multi-day swing) scanner on/off toggle.';
