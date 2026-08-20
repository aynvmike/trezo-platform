NOVA BOT TRADE RULES — REVISED VERSION
Generated: 2026-05-20
Revision Focus: Accuracy, profitability, risk control, execution quality, and paper-trading validation.

IMPORTANT NOTES
- A 100% setup score is not an order trigger.
- A trade can only be placed after the automation switch, broker mode, market window, symbol list, account risk filters, liquidity filters, strategy filters, and order-building rules all pass.
- Live auto-trading remains blocked. Current automation is intended for Alpaca paper mode only.
- Options trading requires Alpaca options access, valid option-chain snapshots, valid Greeks, current quotes, and multi-leg order support.
- Missing market data, stale quotes, missing spread data, or missing risk calculations must block the trade.
- The bot should be designed to reject most signals. Accuracy improves when weak, late, illiquid, or overextended setups are filtered out.

============================================================
1. SYSTEM SAFETY RULES
============================================================

Automation requirements:
- Bot must be running.
- Paper Auto must be enabled.
- Broker must be in paper mode.
- Market must be open.
- Symbol must be in the approved Paper Auto-Trade Symbols list.
- Symbol cannot already have an open position.
- Symbol cannot already have an open order.
- Required price, spread, quote, and volume data must exist.
- If any required data is missing, stale, or invalid, reject the trade.

Broker/account safety:
- Live auto-trading is blocked.
- Broker mode must be confirmed as paper before any auto-order is built.
- Bot must verify buying power before order submission.
- Bot must verify account equity before risk sizing.
- Bot must reject orders that exceed account risk limits.
- Bot must not assume static day-trading rules; broker/account restrictions should be read dynamically when available.

Daily kill-switch rules:
- Stop all new trades for the day if account equity is down 3% intraday.
- Stop all new trades for the day if the strategy is down 2R on the day.
- Stop all new trades for the day after 3 consecutive losing trades.
- Stop all new trades if average slippage exceeds expected slippage by 2x.
- Stop all new trades if market data quality becomes unreliable.
- Stop all new trades if broker order rejects exceed 3 in one session.

Weekly risk control:
- Stop all new trades for the week if account equity is down 6% from the weekly starting balance.
- Resume trading only after manual review or the next defined reset period.

============================================================
2. MARKET REGIME FILTER
============================================================

Before any trade is considered, classify the market environment.

Market regime categories:
- Bull trend day
- Bear trend day
- Range/chop day
- High-volatility reversal day
- Low-volume/no-trade day

Required market checks:
- SPY trend relative to VWAP.
- QQQ trend relative to VWAP.
- SPY/QQQ 5-minute candle direction.
- Market breadth or sector confirmation when available.
- Volatility condition when available.
- Major scheduled news filter.

Long trade market filter:
- Prefer long trades only when SPY or QQQ is above VWAP and not selling off.
- If SPY and QQQ are below VWAP, block bullish trades unless the symbol shows exceptional relative strength.

Short trade market filter:
- Prefer short trades only when SPY or QQQ is below VWAP and not rallying.
- If SPY and QQQ are above VWAP, block bearish trades unless the symbol shows exceptional relative weakness.

Chop filter:
- Reduce size by 50% or block trades when SPY/QQQ repeatedly cross VWAP.
- Block breakout trades in low-volume sideways conditions.
- Require stronger volume and candle confirmation on choppy days.

Major event filter:
- Reject new trades within 30 minutes before or after major scheduled market-moving events, when available.
- Examples include FOMC, CPI, PPI, rate decisions, major jobs reports, and major Fed speeches.
- Reject trades on symbols with earnings before the planned holding period ends, unless an earnings strategy is explicitly enabled.

============================================================
3. SYMBOL QUALITY FILTERS
============================================================

Stock liquidity requirements:
- Average daily volume should be greater than 1,000,000 shares.
- Stock price should be greater than $5.
- Bid/ask spread data must exist.
- Preferred stock spread: below 0.15%.
- Hard stock spread rejection: above 0.30%.
- Reject trade if spread data is missing.
- Reject trade if quote is stale.
- Reject trade if current volume is abnormally low for the time of day.

Symbol event filters:
- Reject if earnings occur before the planned exit or before options expiration.
- Reject if the stock is halted or recently halted.
- Reject if the stock is moving due to merger, buyout, FDA decision, bankruptcy, delisting, or other binary event unless explicitly allowed.
- Reject if the stock has abnormal news risk and the strategy is not designed for news trading.

Time-adjusted volume:
- Use time-adjusted relative volume instead of a generic volume ratio.
- A 1.2x volume reading at 9:40 AM should not be treated the same as 1.2x at 2:30 PM.
- Opening volume should be compared against prior 9:30 to 9:35 candles only.
- Intraday volume should be compared against the same time-of-day window across prior sessions.

============================================================
4. GENERAL STOCK SCORE RULES — REVISED
============================================================

Original score inputs were:
- Above VWAP: 20 points
- EMA20 above EMA50: 20 points
- RSI between 45 and 65: 15 points
- MACD bullish: 20 points
- Volume ratio at least 1.2x: 15 points
- Bollinger position below 80%: 10 points

Revised scoring principle:
- Do not allow a trade simply because 4 of 6 checks pass.
- VWAP, market direction, volume, liquidity, and overextension checks should be mandatory.
- Similar indicators should not be allowed to create false confidence.
- Trend strategies, breakout strategies, and mean-reversion strategies should use separate scoring models.

Mandatory long-trade setup requirements:
- Price is above VWAP.
- SPY/QQQ market filter does not oppose the trade.
- Time-adjusted relative volume passes.
- Spread data exists and passes.
- Price is not overextended from VWAP or ATR.
- Stock is not near a major binary event.
- Trade can be sized with defined risk.

Mandatory short-trade setup requirements:
- Price is below VWAP.
- SPY/QQQ market filter does not oppose the trade.
- Time-adjusted relative volume passes.
- Spread data exists and passes.
- Price is not overextended from VWAP or ATR.
- Stock is not near a major binary event.
- Trade can be sized with defined risk.

Trend confirmation:
- EMA20 above EMA50 may confirm a long trend.
- EMA20 below EMA50 may confirm a short trend.
- EMA slope should be considered in addition to EMA crossover.
- MACD should be treated as confirmation, not a primary trigger.

RSI rules:
- RSI between 45 and 65 is acceptable for long continuation setups.
- RSI above 70 should block chasing unless strategy specifically allows momentum continuation.
- RSI below 30 should block short chasing unless strategy specifically allows downside momentum continuation.
- RSI alone should not trigger a trade.

Bollinger rules:
- Reject long trades if price is too far above the upper Bollinger Band.
- Reject short trades if price is too far below the lower Bollinger Band.
- Bollinger width should be measured as a percentage or percentile, not as a fixed raw number.
- Suggested blocker: reject if Bollinger width is above the symbol's 80th percentile over the last 60 sessions unless a high-volatility strategy is enabled.

============================================================
5. STANDARD PAPER STOCK AUTO-TRADE RULES — REVISED
============================================================

Automation requirements:
- Bot must be running.
- Paper Auto must be enabled.
- Broker must be in paper mode.
- Market must be open.
- Time window: 9:30 AM to 4:00 PM ET, Monday through Friday.
- Symbol must be in the Paper Auto-Trade Symbols list.
- Symbol cannot already have an open position or open order.
- Required liquidity and spread data must exist.

Suggested paper-testing daily limits:
- Max standard auto-trades per day: 5 to 8.
- Max dollars per standard auto-trade: $1,000 or lower during testing.
- Increase daily trade cap only after at least 100 tracked trades show positive expectancy.

Risk and bracket rules:
- Bracket order requires stop loss and take profit.
- Max account risk target during testing: 0.5% to 1% per trade.
- Hard max account risk ceiling: 2% per trade.
- Preferred reward/risk: at least 1.5R.
- Scalping reward/risk of 1.2R is allowed only after data proves the setup has a high enough win rate.
- Reject any trade that cannot produce a valid bracket plan.

Stop placement:
- Stop should be based on structure, VWAP, ATR, or invalidation level.
- For intraday trades, avoid using a 15% stop unless the strategy is explicitly swing-based.
- Suggested day-trade max stop: 1.0x to 1.5x ATR on the active timeframe.
- Reject trade if the required stop is wider than allowed risk.
- Reject trade if position size becomes too small or too large due to stop placement.

Take-profit rules:
- Default target should be at least 1.5R.
- Partial profit-taking may be allowed at 1R if the remaining position is protected.
- Full take-profit should be based on resistance, support, VWAP extension, or R multiple.
- Avoid holding for unrealistic targets after momentum fades.

Day-trade management settings:
- Force-exit time: 3:45 PM ET.
- Max day-trade hold: 90 minutes.
- Stagnation check: 75 minutes.
- Stagnant profit threshold: 0.25R.
- If trade has not reached at least 0.25R by stagnation check, reduce, tighten stop, or exit.
- If price closes against VWAP after entry, evaluate early exit.

============================================================
6. OPENING RANGE BREAKOUT ALERT RULE — REVISED
============================================================

Alert name:
- Opening Range Breakout

Market/time requirements:
- Monday through Friday only.
- Opening range is measured from the first 5-minute candle of the regular session: 9:30 AM to 9:35 AM ET.
- Alerting may continue until 12:00 PM ET.
- Auto-trading should be more restrictive than alerting.

Preferred ORB auto-trade window:
- Best window: 9:35 AM to 10:30 AM ET.
- Reduced-size window: 10:30 AM to 11:30 AM ET.
- No new ORB auto-trades after 11:30 AM ET unless manually approved.

Range:
- Range high = high of the 9:30 5-minute candle.
- Range low = low of the 9:30 5-minute candle.
- Opening range height should be compared against ATR.
- Reject ORB if opening range is too small and likely to create noise.
- Reject ORB if opening range is too large and likely already exhausted the move.

Suggested range quality:
- Opening range height should be between 0.25 ATR and 1.25 ATR.
- If range is less than 0.25 ATR, breakout may be too noisy.
- If range is greater than 1.25 ATR, breakout may be overextended.

Breakout confirmation:
- Confirmation uses completed 1-minute candles.
- Alert fires after 2 completed 1-minute candles close outside the range.
- Both candles must close on the same side:
  - Higher breakout: both closes above range high.
  - Lower breakout: both closes below range low.
- Only one opening-range alert per stock per day.

Additional ORB quality filters:
- Breakout candle volume must be above time-adjusted average.
- Price must be on the correct side of VWAP.
- SPY/QQQ market filter must not oppose the breakout.
- Reject long ORB if price is extended more than 2 ATR from VWAP.
- Reject short ORB if price is extended more than 2 ATR from VWAP.
- Avoid ORB trades caused by abnormal gap/news unless the strategy explicitly supports news breakouts.

Alert display:
- Higher breakout alerts are green with an up arrow.
- Lower breakout alerts are red with a down arrow.

Discord:
- ORB Discord alerts may bypass normal Discord post limits.
- However, ORB alerts should still be ranked by quality to avoid noise.

============================================================
7. OPENING RANGE BREAKOUT OPTIONS TRADE RULES — REVISED
============================================================

Stock criteria comes first:
- The stock must trigger the Opening Range Breakout alert before an options trade is considered.
- The ORB alert must pass the added ORB quality filters.
- The underlying stock must pass liquidity, event, market regime, and spread filters.

Automation requirements:
- Paper Auto must be enabled.
- Broker must be in paper mode.
- Market must be open.
- The stock cannot already have an open position or open order.
- Daily ORB strategy trade count must be below the cap.
- Remaining ORB daily risk budget must be enough for the selected spread.
- Options chain, quote, Greeks, bid/ask, volume, and open interest data must exist.

Suggested paper-testing ORB limits:
- Max ORB trades per day: 3 to 5.
- ORB daily risk budget: 4% to 6% of account equity.
- Max risk per ORB options trade during testing: 0.5% to 1% of account equity.
- Hard rejection above 2% risk per options trade.
- Increase limits only after at least 100 tracked ORB options trades show positive expectancy.

Options selection:
- Bullish setup: sell put spread below support.
  - Current support reference: opening range low.
  - Additional support references may include VWAP, prior day high/low, premarket high/low, and intraday structure.
- Bearish setup: sell call spread above resistance.
  - Current resistance reference: opening range high.
  - Additional resistance references may include VWAP, prior day high/low, premarket high/low, and intraday structure.
- Neutral setup: iron condor outside expected move.
  - Use only when the market regime supports range-bound trading.
  - Do not use neutral setup when the ORB breakout is strong and directional.

Expiration/DTE rules:
- Avoid 0DTE options during early testing.
- Preferred ORB options testing window: 7 to 21 DTE.
- Preferred slower swing credit-spread window: 30 to 45 DTE.
- Reject expiration if liquidity is poor.
- Reject expiration if earnings occur before expiration unless explicitly allowed.
- Reject expiration if ex-dividend risk affects short calls.

Short strike:
- Short strike target delta: 0.15 to 0.30 absolute delta.
- Candidate selection prefers a short strike near 0.22 delta.
- Reject if short strike is too close to the opening range, VWAP, or current price.
- Reject if short strike delta moves above 0.40 after entry and exit rules are triggered.

Premium:
- Target credit: roughly 25% to 35% of spread width.
- For iron condors, premium ratio applies to the combined condor credit.
- Reject if credit is too low to justify the risk.
- Reject if credit is unusually high due to bad quotes or event risk.

Options liquidity filter:
- Bid/ask spread must be less than or equal to 10% to 15% of the option midpoint.
- Open interest should be at least 500 on the short leg.
- Volume should be at least 100 on the short leg.
- Quote age should be 5 seconds or less.
- Reject if bid is 0.00.
- Reject if midpoint cannot be calculated.
- Reject if the spread cannot be priced reasonably as a net-credit order.

Risk:
- Spread max risk = (spread width - credit) x 100.
- Max risk per options trade during testing: 0.5% to 1% of account equity.
- Absolute ceiling: 2% of account equity.
- ORB daily risk budget also limits total risk allocated across all ORB trades.
- Avoid stacking multiple correlated spreads in the same direction across similar symbols.

Order type:
- Alpaca multi-leg option order.
- Entry order is a net-credit limit order.
- Legs are opened as:
  - Short leg: sell_to_open
  - Long hedge leg: buy_to_open
- Reject market orders for options.
- Use limit orders at or near midpoint.
- Cancel unfilled orders after a defined timeout.
- Do not chase poor fills beyond the allowed slippage threshold.

Early profit exit:
- On entry fill, Nova submits or prepares a closing multi-leg limit order.
- Take-profit close target is about 50% of collected credit.
- Example: if credit collected is $1.00, target close debit is about $0.50.
- Goal is to take profit early and avoid holding every trade to expiration.

Loss and invalidation exits:
- Close spread if loss reaches 1.0R.
- Close spread if spread price reaches 2x the entry credit.
- Close spread if underlying closes back inside the opening range after breakout.
- Close spread if short strike delta moves above 0.40.
- Close spread before end of day if the setup is intended as an intraday ORB trade.
- Close or reduce if the market regime flips against the trade.
- Close if quote quality becomes unreliable and risk cannot be measured.

Assignment/event risk:
- No short calls through ex-dividend date.
- No short options through earnings unless explicitly allowed.
- No options trades on halted or recently halted stocks.
- No options trades around merger, buyout, FDA, bankruptcy, or other binary events unless explicitly allowed.

============================================================
8. UNUSUAL OPENING VOLUME ALERT RULE — REVISED
============================================================

Time window:
- Runs on weekdays between 9:35 AM and 9:40 AM ET.
- Uses the 9:30 5-minute candle.

Comparison:
- Compares today's 9:30 to 9:35 opening volume to the same opening 5-minute window from prior sessions.
- Requires at least 20 historical opening bars.
- Use median or trimmed average instead of simple average.
- Avoid allowing one abnormal prior day to distort the average.

Alert thresholds:
- 1.5x opening volume = unusual.
- 2.0x opening volume = strong.
- 3.0x or higher opening volume = major attention.
- 0.6x or lower opening volume = unusually low interest.

Limit:
- Alerts are sorted by impact and capped to the top 10 candidates.

Usage:
- Unusual opening volume is a ranking and attention filter.
- It should not automatically trigger a trade.
- Use unusual volume to prioritize ORB and momentum candidates.

============================================================
9. DISCORD ALERT LIMITS — REVISED
============================================================

Normal 5-minute stock signal Discord alerts:
- Weekdays, 9:30 AM to 4:00 PM ET.
- Limit: 5 stocks per 15-minute window.
- Same symbol is blocked from reposting in the same 15-minute window.

Daily-chart Discord alerts:
- Weekdays, 8:00 AM to 4:30 PM ET.
- Limit: 5 stocks per 15-minute window.

Unusual-volume Discord alerts:
- Weekdays, 9:35 AM to 9:40 AM ET.
- Limit: 10 stocks.
- Same symbol is blocked from reposting for that day's unusual-volume window.

Opening Range Breakout Discord alerts:
- Weekdays, 9:35 AM to 12:00 PM ET.
- ORB alerts may bypass rolling Discord post limits.
- ORB alerts should still be ranked by quality.
- Send ORB alerts only if relative volume, spread, liquidity, market filter, and ORB range quality pass.

Suggested ORB alert ranking:
- Relative volume strength.
- Clean breakout candle structure.
- Distance from VWAP.
- Market alignment.
- Tight spread.
- Strong options liquidity if options trade is possible.
- Prior success rate of the symbol/setup.

============================================================
10. COMMON REASONS A TRADE DOES NOT PLACE — UPDATED
============================================================

A trade should not place if:
- Paper Auto is off.
- Broker is not in paper mode.
- Market is closed.
- Symbol is only on the watchlist and not in Paper Auto-Trade Symbols.
- Symbol already has an open position or open order.
- Daily trade cap has been reached.
- Daily loss kill switch has been triggered.
- Weekly loss limit has been triggered.
- Consecutive loser pause is active.
- Required market data is missing.
- Required spread data is missing.
- Quotes are stale.
- Stock setup passes score but fails mandatory filters.
- Market regime filter opposes the trade.
- Symbol liquidity is too weak.
- Spread is too wide.
- Price is overextended from VWAP or ATR.
- Earnings/event risk is active.
- Standard stock setup cannot build a valid bracket plan.
- Stop is too wide for the account risk limit.
- Reward/risk is below required threshold.
- ORB alert fires but fails range-quality filters.
- ORB alert fires too late in the day.
- ORB alert fires but options spread fails DTE, liquidity, delta, premium, or risk filters.
- ORB daily risk budget is already used.
- Options chain or Greeks are missing.
- Option quote is stale.
- Option bid/ask spread is too wide.
- Alpaca rejects the order because account permissions, options level, symbol, buying power, or order parameters are not accepted.
- Slippage/fill-quality rules are violated.

============================================================
11. PERFORMANCE LOGGING AND FEEDBACK LOOP
============================================================

The bot should log every alert, not just executed trades.

For every alert, record:
- Timestamp.
- Symbol.
- Strategy name.
- Direction.
- Market regime.
- SPY/QQQ trend.
- Price relative to VWAP.
- Volume ratio and time-adjusted volume ratio.
- Spread percentage.
- ATR distance from VWAP.
- Setup score.
- Which mandatory filters passed or failed.
- Whether trade was taken.
- Reason trade was rejected, if rejected.

For every stock trade, record:
- Entry price.
- Stop price.
- Take-profit price.
- Position size.
- Account risk percentage.
- Planned R.
- Exit price.
- Exit reason.
- Maximum favorable excursion.
- Maximum adverse excursion.
- Final R result.
- Slippage.
- Hold time.

For every options trade, record:
- Strategy type.
- Expiration.
- DTE.
- Short strike.
- Long strike.
- Short strike delta.
- Credit received.
- Spread width.
- Max risk.
- Premium-to-width ratio.
- Option volume.
- Open interest.
- Bid/ask spread.
- Entry fill quality versus midpoint.
- Exit debit.
- Profit/loss.
- Exit reason.
- Short strike delta at exit.
- Whether underlying invalidation occurred.

Review schedule:
- Review performance after every 25 trades.
- Do not change rules after one bad trade.
- Adjust rules only after enough trades show a reliable pattern.
- Separate results by strategy, symbol, time of day, and market regime.

Key performance metrics:
- Win rate.
- Average win.
- Average loss.
- Profit factor.
- Expectancy per trade.
- Max drawdown.
- Average slippage.
- Fill rate.
- Rejection reason frequency.
- Best and worst time windows.
- Best and worst market regimes.
- Best and worst symbols.

============================================================
12. RECOMMENDED TESTING PHASES
============================================================

Phase 1: Signal-only logging
- No auto-orders.
- Track every signal and rejection reason.
- Minimum sample: 100 alerts per strategy.

Phase 2: Paper trading with reduced risk
- Enable paper orders only.
- Max standard trades per day: 5 to 8.
- Max ORB options trades per day: 3 to 5.
- Max risk per trade: 0.5% to 1%.
- Keep daily kill switch active.

Phase 3: Paper trading optimization
- Compare results by strategy and market regime.
- Remove weak symbols.
- Tighten poor-performing time windows.
- Add rejection rules where losses cluster.
- Do not increase size until expectancy is positive.

Phase 4: Live-readiness review
- Only consider live trading after:
  - At least 100 executed paper trades per strategy.
  - Positive expectancy.
  - Stable drawdown profile.
  - Slippage assumptions tested.
  - Order rejects understood.
  - Broker limitations documented.
  - Manual override process tested.

============================================================
13. CORE PRINCIPLE
============================================================

The goal is not to make Nova Bot trade more often.

The goal is to make Nova Bot reject weak trades and only act when the following align:
- Market regime
- Symbol liquidity
- Directional setup
- Volume confirmation
- VWAP/structure confirmation
- Options liquidity, if applicable
- Defined risk
- Clean order construction
- Positive expectancy based on logged results

A profitable bot should say "no trade" most of the time.
