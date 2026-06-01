-- =====================================================================
-- Trezo — Phase 13b: Tunable Pattern Engine weights
-- =====================================================================
-- Lets the user tilt the 10 Pattern Engine factor weights from their
-- Bot Tuning page. The default (NULL / empty) keeps the built-in
-- fair-weighted 8–12 point split (#121 transparency follow-up).
--
-- JSONB shape: {"trend": 12, "momentum": 10, "macd": 12, "volume": 10,
--               "breakout": 12, "candle_pattern": 10, "bb_position": 8,
--               "vwap_alignment": 8, "market_alignment": 8,
--               "iv_environment": 10}
-- =====================================================================

alter table public.bot_settings
  add column if not exists pattern_weights jsonb;

comment on column public.bot_settings.pattern_weights is
  'Optional per-factor weight overrides for the Pattern Engine scoring. NULL = use the built-in weights (trend/macd/breakout 12, momentum/volume/candle/iv 10, bb/vwap/market 8).';
