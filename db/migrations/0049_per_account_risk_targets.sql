-- 0049: per-account risk targets (2026-08-09, Mike)
--
-- Mike: "everything will be in proportion to the account so it can be what
-- risk is acceptable by the user... target risk of 4 percent to 10 percent
-- so the account can be able to trade futures now."
--
-- FUTURES DID NOT NEED THE RAISE. Measured against real contract specs, 4%
-- on the 75k book already allows 30 MES contracts and margin binds first on
-- MNQ and MBT. The old blocker was contract granularity against a $4,900
-- account, and account size already solved it. So the higher number is not
-- a futures prerequisite -- it is a deliberate risk experiment, and is set
-- up as one.
--
-- WHY THESE VALUES -- a controlled comparison, not three arbitrary numbers:
--   primary 4%  ($194/trade)   the running baseline, untouched
--   25k     4%  ($1,000/trade) SAME risk, MORE capital -> isolates capital
--   75k    10%  ($7,500/trade) the high-risk / futures book
--
-- ⚠️ WHAT THE EVIDENCE SAYS ABOUT 10%. Vince optimal_f over the 196 real
-- closed trades returns 0.001 -- the search floor -- because the measured
-- geometric mean is below 1.0 at EVERY fraction: 98 wins, 98 losses,
-- -$386.75 net. On a negative expectancy, raising f multiplies loss and
-- drawdown together, it does not buy return:
--        4% -> -0.073%/trade, 13.9% max drawdown
--       10% -> -0.190%/trade, 32.4% max drawdown
-- That series is contaminated -- it spans the scalp exit defect, the
-- kill-switch that was 33x too tight, and the execution leaks, all since
-- repaired -- so it measures a partly-broken system rather than the
-- strategy. The 75k book is where that can be tested without risking the
-- baseline. Revert with the same UPDATE and 0.04.
--
-- These are USER SETTINGS. Once the account switcher ships they belong in
-- Bot Tuning; this migration only seeds them, because there is no UI to
-- pick an account yet.

-- ⚠️⚠️ RISK AND max_open INTERACT -- changing one alone is incoherent.
-- 10% x 14 concurrent = 140% of the book at risk, which cannot happen: you
-- cannot lose more than you have. And this is not a theoretical tail for
-- this book -- portfolio_risk.py measured 14 open positions as 6.83
-- EFFECTIVE bets with 64% in one factor, so crypto positions stop out
-- together, not independently. The worst case is the realistic one.
-- So max_open drops with the raise, holding total exposure near the other
-- two books (10% x 6 = 60% vs 4% x 14 = 56%). One variable moves: the size
-- of each bet. The number of bets stays comparable.

BEGIN;

UPDATE bot_settings
   SET risk_per_trade_pct = 0.10,
       max_open_positions = 6
 WHERE user_id = '49acafdd-1c86-4740-a1b1-f94aa7abce08';   -- Trezo Inc. 2 - 75k

UPDATE bot_settings
   SET risk_per_trade_pct = 0.04
 WHERE user_id = '6ce61054-7ffd-41b5-80c3-1cd0220c79eb';   -- Trezo Inc. 3 - 25k

COMMIT;

SELECT t.label,
       p.starting_capital_usd,
       s.risk_per_trade_pct,
       round(p.starting_capital_usd * s.risk_per_trade_pct, 2) AS risk_dollars_per_trade,
       s.max_open_positions,
       round(p.starting_capital_usd * s.risk_per_trade_pct
             * s.max_open_positions, 2)                    AS total_at_risk_if_all_open
FROM trading_accounts t
JOIN paper_accounts p ON p.user_id = t.account_key
JOIN bot_settings   s ON s.user_id = t.account_key
ORDER BY p.starting_capital_usd;
