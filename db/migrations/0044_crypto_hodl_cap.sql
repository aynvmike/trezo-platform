-- 0044: crypto HODL per-coin cap + accumulation cooldown (2026-06-13, crypto Part 2)
-- Makes two crypto Part 2 knobs tunable from Bot Tuning. NOTE: the agent
-- code already enforces these via graceful defaults (r.get(col, default)),
-- so this migration is OPTIONAL / non-blocking -- it only makes the values
-- editable per-user from the dashboard. Defaults match the code defaults.
--   hodl_per_coin_cap_pct          - max TOTAL open exposure to one coin
--                                    as a share of equity (0.10 = 10%).
--   crypto_accumulate_cooldown_hours - min hours between HODL/DCA adds on
--                                    the same coin (turns "buy the dip"
--                                    into "across days").
ALTER TABLE bot_settings
  ADD COLUMN IF NOT EXISTS hodl_per_coin_cap_pct numeric NOT NULL DEFAULT 0.10;
ALTER TABLE bot_settings
  ADD COLUMN IF NOT EXISTS crypto_accumulate_cooldown_hours numeric NOT NULL DEFAULT 18;
