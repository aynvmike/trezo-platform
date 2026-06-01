-- 0029 — Wheel auto-execute toggle.
--
-- When ON, the Options Scanner's _run_wheel() pass places real CSP /
-- CC orders against Alpaca instead of only emitting suggestions.
-- Routes through the same /wheel/place-leg primitives the manual
-- button uses (live_option_pick + submit_option_order), so the only
-- difference is who clicks "Place" - the user or the bot.
--
-- Safety gates the agent enforces before any auto-fire:
--   1. wheel_auto_execute = true (this setting)
--   2. User has Alpaca configured (OAuth or env keys)
--   3. Alpaca options approval level >= 1 (covered)
--   4. No open position on the same underlying
--   5. Account not in trading_halted state (kill-switch)
--   6. Consecutive-loss limit not tripped
--
-- Default OFF so existing installs keep manual-button behavior. Mike
-- has Level 3 Alpaca paper approval ready to test against.

alter table bot_settings
  add column if not exists wheel_auto_execute boolean not null default false;

comment on column bot_settings.wheel_auto_execute is
  'When true and Alpaca options approval >= 1, the Options Scanner auto-fires Wheel CSP/CC orders via the same primitives the manual Place button uses. Default off.';
