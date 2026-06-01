-- =====================================================================
-- Trezo - terse signal format toggle (Mike 2026-05-31)
-- =====================================================================
-- Per-user opt-in for the compact, structured signal format. When ON,
-- signal cards default to the 8-line schema (Ticker / Bias / Trade
-- Type / Strike & Expiration / Entry Range / Exit Target Stop /
-- Confidence Level / Reasoning). Verbose body is still mounted in
-- the DOM; user can flip per-card. Mobile viewport auto-defaults to
-- compact regardless of the setting.
--
-- Pairs with expert_mode_enabled but does not require it. Default
-- false so opt-in is conscious.
-- =====================================================================

alter table public.bot_settings
  add column if not exists terse_format_enabled boolean not null default false;

comment on column public.bot_settings.terse_format_enabled is
  'When ON, signal cards default to the compact 8-line trader format. Per-card flip available. Mobile viewport auto-defaults to compact regardless of this setting.';
