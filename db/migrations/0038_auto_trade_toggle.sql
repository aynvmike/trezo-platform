-- =====================================================================
-- Trezo - auto-trade toggle (Mike 2026-06-01)
-- =====================================================================
-- The user-facing kill switch for bot execution. When OFF, every
-- signal still scores + every approval still fires through the
-- agent bus + the post-mortem ledger still records the would-have-
-- done. But no open_position call lands. Pure learn-only mode.
--
-- Default ON for paper accounts. When TRADING_MODE=live is later
-- wired, onboarding will reset this to OFF until the user explicitly
-- opts back in - real money execution should never be on by default.
-- =====================================================================

alter table public.bot_settings
  add column if not exists auto_trade_enabled boolean not null default true;

comment on column public.bot_settings.auto_trade_enabled is
  'When ON, approved signals route to the paper/live engine. When OFF, signals + post-mortem still log; nothing actually trades. The user-facing "let the bots actually act" switch.';
