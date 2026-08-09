-- 0046: seed state rows for the 25k and 75k books (2026-08-09, multi-account)
-- 0045 registered the books in trading_accounts. They still had NO state:
-- no paper_accounts row (equity, day-start baseline, halt flags) and no
-- bot_settings row (posture, risk, lanes). Two consequences if left:
--   * the kill-switch takes its DAILY BASELINE from equity. A book with no
--     row reads 0, and a 3% drawdown on 0 halts on the first cent. This is
--     the same failure mode as 2026-08-07, where a $151 baseline against a
--     $4,901 account halted after a $4.52 loss.
--   * settings would fall back to code defaults (max_open 3, risk 5%,
--     TCS 70) rather than anything the user chose -- and a 5% risk on the
--     75k book is $3,750 a trade.
-- So both rows are seeded, and bot_settings is COPIED FROM THE PRIMARY --
-- the config already tuned and running -- so the books start identical and
-- differ only where the user changes them in the UI.
--
-- ⚠️ NOTE THE ABSOLUTE NUMBERS. Copying the primary keeps the same
-- PERCENTAGES, which on a bigger book means much bigger dollar risk:
--   risk_per_trade_pct 0.04  ->  primary ~$194,  25k $1,000,  75k $3,000
-- That is the intended "same strategy, more capital" comparison, but it is
-- a decision. Change it per account in Bot Tuning, not here.
--
-- Idempotent: ON CONFLICT DO NOTHING on both inserts. Safe to re-run.

-- 1. paper_accounts -- fresh books, all cash, baselines set to face value
INSERT INTO paper_accounts (
  user_id, starting_capital_usd, current_cash_usd, vault_balance_usd,
  ytd_realized_pnl_usd, today_realized_pnl_usd, week_realized_pnl_usd,
  daily_target_hit_today, last_reset_date, day_start_equity_usd,
  week_start_equity_usd, week_start_date, consecutive_losses,
  trading_halted, created_at, updated_at
) VALUES
  ('6ce61054-7ffd-41b5-80c3-1cd0220c79eb', 25000, 25000, 0,
   0, 0, 0, false, CURRENT_DATE, 25000, 25000, CURRENT_DATE, 0,
   false, now(), now()),
  ('49acafdd-1c86-4740-a1b1-f94aa7abce08', 75000, 75000, 0,
   0, 0, 0, false, CURRENT_DATE, 75000, 75000, CURRENT_DATE, 0,
   false, now(), now())
ON CONFLICT (user_id) DO NOTHING;

-- 2. bot_settings -- copy every column from the primary, new user_id only.
-- jsonb_populate_record copies the whole row, so this keeps working if the
-- table gains columns later (it has 32 today).
INSERT INTO bot_settings
SELECT (jsonb_populate_record(
          NULL::bot_settings,
          to_jsonb(b) || jsonb_build_object(
            'user_id', '6ce61054-7ffd-41b5-80c3-1cd0220c79eb')
        )).*
FROM bot_settings b
WHERE b.user_id = 'cf1b0460-039d-40ac-adc8-7ca3ef17c5bb'
ON CONFLICT (user_id) DO NOTHING;

INSERT INTO bot_settings
SELECT (jsonb_populate_record(
          NULL::bot_settings,
          to_jsonb(b) || jsonb_build_object(
            'user_id', '49acafdd-1c86-4740-a1b1-f94aa7abce08')
        )).*
FROM bot_settings b
WHERE b.user_id = 'cf1b0460-039d-40ac-adc8-7ca3ef17c5bb'
ON CONFLICT (user_id) DO NOTHING;

-- 3. Confirmation
SELECT t.label,
       p.starting_capital_usd,
       p.day_start_equity_usd,
       s.account_posture,
       s.max_open_positions,
       s.risk_per_trade_pct,
       round(p.starting_capital_usd * s.risk_per_trade_pct, 2) AS risk_dollars_per_trade
FROM trading_accounts t
LEFT JOIN paper_accounts p ON p.user_id = t.account_key
LEFT JOIN bot_settings   s ON s.user_id = t.account_key
ORDER BY p.starting_capital_usd;
