# TREZO — Strategy Rules

## Overview
All trading strategies in Trezo with exact rules, parameters, and execution logic. These are not suggestions — they are enforceable rules the bot follows.

---

## 1. SMALL TRADES MOMENTUM STRATEGY (STMS)

### Origin
Trezo proprietary strategy. Adapted from proven small-cap momentum principles, calibrated for the founder's demonstrated strengths.

### Purpose
Capture explosive small-cap momentum moves during the most volatile market hours.

### Trading Window
**7:00 AM – 11:00 AM EST only.**
Outside this window: scanner active, no trades.

### Entry Criteria
ALL must be true:

| Criterion | Requirement |
|-----------|-------------|
| Stock Price | $1.00 – $20.00 |
| Daily Move | Already up 10%+ on the day |
| Relative Volume | 5x average minimum |
| Catalyst | Required — news event moving stock |
| Float | Under 20 million shares |
| Pattern Detected | Bull Flag, Flat Top, or Micro-Pullback |
| Trade Confidence Score | 750+ (or user's threshold) |

### Position Sizing
- Risk per trade: 5% of stock account
- Stop distance: 5% below entry
- Position size = (Account × 0.05) ÷ (Entry × 0.05)

### Stop Loss
- Hard stop at 5% below entry
- Trailing stop activates after 5% profit
- Time stop: close all by 11:00 AM EST

### Profit Targets
- Target 1 (50% of position): 10% above entry
- Target 2 (remainder): trail with 5% trailing stop

### Catalysts That Qualify
- Earnings beat/miss with significant move
- FDA approval
- Drug trial results
- Major contract announcement
- Uplisting to NYSE/NASDAQ
- Short squeeze setup
- Analyst upgrade to Buy
- CEO buyback announcement
- Strategic partnership

### Catalysts That DON'T Qualify
- Generic press releases
- Pump-and-dump promotions
- Social media hype without fundamentals
- Old news being recycled
- Insider selling

### After 11 AM (Scanner Mode)
- Continue scanning for next-day setups
- Log all qualifying tickers
- Build watchlist for next morning
- No trades executed

---

## 2. CRYPTO BOT STRATEGY (24/7)

### Coins Traded
- XRP (cap: $2,536.69, stop: 3%, target: 6%)
- ETH (cap: $1,267.00, stop: 2.5%, target: 5%)
- SOL (cap: $833.01, stop: 4%, target: 8%)

### Three Adaptive Modes

**SCALP Mode**
- Activated when: RSI 40-68, normal volatility
- Holding time: 1-6 candles (5min-30min)
- Target: 2.5-3%
- Stop: tight at entry minus 1.5%
- Volume requirement: 1.2x average

**SWING Mode**
- Activated when: Strong trend + volume + BB width > 2.5%
- Holding time: hours to days
- Target: 10-15%
- Stop: 5% from entry
- Trailing stop after 5% profit

**DCA Mode**
- Activated when: RSI < 35 (buy) or > 68 (sell)
- Slow accumulation/distribution
- 4 entries spaced over 24 hours
- Target: returning to mean (50 RSI)

### Indicators Used
- RSI(14)
- MACD(12,26,9)
- Bollinger Bands(20,2)
- VWAP (session)
- EMA 20 / EMA 50
- Volume ratio

### Risk Management
- 5% per trade max
- 10% daily loss limit per coin
- 10% daily loss total = bot halts
- Anti-averaging: never add to losing positions

---

## 3. THE DIVIDEND WHEEL

### Concept
Generate continuous income from dividend stocks using Cash-Secured Puts and Covered Calls in rotation.

### Starting Capital
$1,000 (slider-adjustable up to 50% of total stock account)

### Stock Selection Criteria
- Stock price: $5 - $50 (affordable 100-share lots)
- Dividend yield: 3%+ preferred
- Stability: Low to moderate volatility
- Liquidity: Options must have decent volume
- No earnings within 14 days of entry

### Recommended Wheel Stocks (by Risk Level)

**Conservative**
- T (AT&T) — 5.8% yield
- KMI (Kinder Morgan) — 6.2% yield
- F (Ford) — 5.5% yield
- AGNC (mREIT) — 14% yield (higher risk)

**Balanced**
- INTC (Intel) — 2.1% yield
- BAC (Bank of America)
- SOFI (no dividend but high premium)
- PFE (Pfizer) — 5% yield

**Aggressive**
- High IV momentum stocks
- AI/semiconductor mid-caps
- Recent IPOs with options

### Wheel Cycle Rules

**Phase 1: Sell Cash-Secured Put**
- Strike: 5-10% below current price
- Expiry: 14-30 days out
- Goal: Collect premium

**Phase 2: If Assigned (Own 100 shares)**
- Hold shares
- Collect dividends
- Move to Phase 3

**Phase 3: Sell Covered Call**
- Strike: 5-10% above cost basis (NEVER below)
- Expiry: 14-30 days out
- Goal: Collect more premium

**Phase 4a: Call Expires Worthless**
- Sell another Covered Call
- Repeat Phase 3

**Phase 4b: Shares Called Away**
- Profit captured
- Return to Phase 1

### Dividend Capture
- Bot monitors ex-dividend dates
- Avoids selling calls that could be exercised before dividend
- Captures dividend then sells call after

---

## 4. OPTIONS ENGINE — 14 STRATEGIES

### Strategy Selection Logic
Bot picks strategy based on:
1. IV Rank (high vs low)
2. Market direction view (bullish/bearish/neutral)
3. Time horizon
4. Account size
5. User risk slider

### Strategy Library

**1. Long Call**
- When: Bullish, low IV, expecting big move
- Duration: 0DTE to 30DTE
- Risk: Limited to premium paid

**2. Long Put**
- When: Bearish, low IV, expecting decline
- Duration: 0DTE to 30DTE
- Risk: Limited to premium paid

**3. Bull Call Spread**
- When: Moderately bullish, defined risk
- Buy lower strike call, sell higher strike call
- Duration: Weekly to monthly

**4. Bear Put Spread**
- When: Moderately bearish, defined risk
- Buy higher strike put, sell lower strike put
- Duration: Weekly to monthly

**5. Iron Condor**
- When: High IV, range-bound market
- Sell OTM call spread + sell OTM put spread
- Duration: Weekly to monthly
- Profit: Stock stays in range

**6. Iron Butterfly**
- When: Very tight range expected
- Sell ATM straddle + buy OTM wings
- Duration: Weekly

**7. Butterfly Spread**
- When: High conviction price target
- Buy/sell ratio at specific strikes
- Duration: Weekly to monthly

**8. Calendar Spread**
- When: Low IV, expecting rise
- Sell near expiry, buy far expiry same strike
- Duration: 2-4 weeks

**9. Straddle**
- When: Big move expected, direction unknown
- Buy ATM call + buy ATM put
- Duration: Earnings plays

**10. Covered Call**
- When: Own 100 shares, neutral-bullish
- Sell call above current price
- Duration: Weekly to monthly

**11. Cash-Secured Put**
- When: Want shares cheaper
- Sell put with cash to back it
- Duration: Weekly to monthly

**12. The Wheel**
- When: Continuous income desired
- CSP → Assigned → Covered Call → repeat
- Duration: Continuous

**13. Poor Man's Covered Call (PMCC)**
- When: Want covered call without 100 shares
- Buy deep ITM long call, sell short call against
- Duration: Monthly

**14. Diagonal Spread**
- When: Time + direction play
- Different strikes + different expiries
- Duration: 2-6 weeks

### Position Sizing Rules

| Account Size | Max Per Contract | Max Contracts |
|--------------|------------------|---------------|
| $500-$1,000 | $50 | 1 |
| $1,000-$2,500 | $100 | 1-2 |
| $2,500-$5,000 | $200 | 3 |
| $5,000+ | 5% of account | 5 |

### ITM/OTM Rules

| Account Size | Allowed |
|--------------|---------|
| Under $1,500 | OTM only |
| $1,500-$3,000 | ATM or slight OTM |
| $3,000+ | ITM allowed if justified |

### Days to Expiry Rules

| Strategy Type | Min DTE | Max DTE |
|---------------|---------|---------|
| Scalp plays | 0 | 5 |
| Day trade | 1 | 14 |
| Wheel plays | 7 | 45 |
| Swing plays | 14 | 60 |
| Conservative | 30 | 90 |

---

## 5. LAYER 7 — EXTENDED STOCK STRATEGY

### 7A: Swing Trading (2-5 Day Holds)

**Setups Traded:**
- Earnings Gap-Up (5-15% over 2-3 days)
- Seasonal Plays (5-10% over 3-5 days)
- Breakout Hold (8-15% over 3-5 days)
- Pullback to EMA50 (5-10% bounce)
- Earnings Continuation (5-12% over 2 days)

**Rules:**
- Risk per trade: 5-10% of allocated capital
- Stop-loss always placed before entry
- Target: 5-10% minimum
- Never hold through earnings (unless earnings is the catalyst)
- Exit at target or stop — no holding for "a little more"

### 7B: Penny Stock Strategy

**Adapted Principles:**
- Only trade stocks in motion (10%+ on the day)
- Catalyst mandatory (Finnhub news API check)
- Low float = explosive (under 20M shares required for A-grade)
- NEVER use market orders (limit only)
- Cut losses at 5-10% (hard stop enforced)
- Never hold overnight on momentum plays
- Wait for breakout confirmation
- Never risk more than 5% per trade
- Bot enforces stops algorithmically
- Never average down on losers

**Patterns Detected:**
- Supernova (explosive spike + volume)
- Stair Stepper (gradual rises with consolidation)
- Breakout from Resistance
- Short Squeeze Setup

**Patterns Avoided:**
- The Crow (gradual decline, low volume)
- The Snore (no movement despite news)

### 7C: Event-Driven Trading

**Events Monitored:**
- Earnings (beat + gap up)
- FDA approvals
- Seasonal retail
- Product launches
- Fed announcement days
- Index rebalancing

**Rules:**
- No new positions on Fed days until after 2PM EST
- Pause bot on index rebalancing days
- Long calls or debit spreads for FDA plays
- Swing long if stock holds above gap on 5-min VWAP

### What Layer 7 Does NOT Do
- Does not scalp (no 5-20 cent intraday trades)
- Does not short sell penny stocks under $1
- Does not play pump-and-dump stocks
- Does not hold losing positions hoping for recovery
- Does not trade oil and gas penny stocks

---

## 6. TRADE CONFIDENCE SCORE (0-1000)

### Scoring Categories

**Technical Analysis (300 points)**
- Candlestick pattern: 100 pts
- Multi-timeframe confluence: 80 pts
- Volume confirmation: 60 pts
- VWAP/EMA alignment: 60 pts

**Options Environment (250 points)**
- IV Rank: 100 pts
- Days to expiry fit: 75 pts
- Bid/ask spread: 75 pts

**Fundamental/Event (200 points)**
- News catalyst: 100 pts
- Earnings proximity: 60 pts
- Corporate event: 40 pts

**Risk/Reward (150 points)**
- R/R ratio quality: 100 pts
- Max loss acceptability: 50 pts

**Market Conditions (100 points)**
- SPY/QQQ alignment: 50 pts
- VIX environment: 50 pts

### Thresholds

| Score | Action |
|-------|--------|
| 750+ | Bot auto-executes |
| 600-749 | Alert user, one-tap approve |
| Below 600 | Skip, log for review |

### User-Adjustable

| Setting | Threshold |
|---------|-----------|
| Conservative | 800+ |
| Balanced (default) | 750+ |
| Aggressive | 650+ |

---

## 7. AGGRESSION/PASSIVE SLIDER

### Conservative (1-3)
- Confidence threshold: 800+
- Risk per trade: 3% of account
- Wheel: High dividend, low vol stocks
- Options: OTM only, defined risk
- Cold market response: Sit tight
- Crypto: DCA bias

### Balanced (4-6) — Default
- Confidence threshold: 750+
- Risk per trade: 5% of account
- Wheel: Medium yield, medium vol
- Options: ATM or slight OTM
- Cold market response: Reduced size
- Crypto: Mixed modes

### Aggressive (7-10)
- Confidence threshold: 650+
- Risk per trade: 7% of account
- Wheel: High premium, high IV stocks
- Options: ITM allowed
- Cold market response: Continue trading
- Crypto: Scalp + Swing bias

---

## 8. ANTI-PATTERN RULES (Hard Blocks)

Based on founder's documented weaknesses, these are HARD BLOCKS:

### Anti-Averaging Rule
**Bot NEVER adds to a losing position.**
- If price moves 15% against entry, position closes
- New entry only allowed after fresh A-grade signal
- "Double down" attempts logged but blocked

### Hard Stop Enforcement
**Every position has a stop set at entry.**
- Stop cannot be moved further from entry
- Stop CAN be tightened as price moves favorably
- Stop hits = immediate exit, no exceptions

### Time Stop
**Every position has a time limit.**
- Day trades close by 3:55 PM EST
- Swing trades close after defined duration
- Options close 5 days before expiry minimum

### Position Limits
**Hard caps that cannot be exceeded:**
- Max 5 simultaneous options positions
- Max 30% in any single sector
- Max 25% in any single crypto
- Max 3% per options trade

### Concentration Override
**If founder's pattern of spreading thin is detected:**
- Bot suggests consolidation
- Cannot open new position with 5 already active
- Forces selection of best opportunities

---

## 9. DAILY OPERATING SCHEDULE

```
05:00 AM  Research Agent: Pre-market scan
06:00 AM  Build STMS watchlist
06:30 AM  Final scanner check
07:00 AM  STMS Stock Bot: TRADING ACTIVE
09:30 AM  Market open: full activity
10:00 AM  Peak STMS hour
11:00 AM  Stock Bot: TRADING WINDOW CLOSED
11:01 AM  After-hours scanner mode
12:00 PM  Options scanner active
04:00 PM  Market close, position review
04:30 PM  Tax ledger update
05:00 PM  Daily report generated
08:00 PM  Strategy Discovery (Phase 3)
10:00 PM  Nightly maintenance
00:00 AM  Crypto bot continues (24/7)
```

---

## 10. STRATEGY-BY-MARKET-CYCLE MATRIX

| Market Cycle | Layer 1 (Crypto) | Layer 2 (STMS) | Layer 3 (Options) | Layer 4 (Wheel) |
|--------------|------------------|----------------|-------------------|-----------------|
| HOT 🔥 | Aggressive scalping | Active scanning | Long calls/debit | Aggressive premiums |
| WARM | Normal operations | Full activity | Mixed strategies | Standard wheel |
| NEUTRAL | DCA bias | Selective entries | Iron condors | Conservative strikes |
| COOL | Reduced size | Selective only | Defensive plays | Continue safely |
| COLD ❄️ | Defensive only | Sit tight | Iron condors only | Pause new entries |
| HIGH VOL ⚡ | Pause new entries | Pause | Iron condors only | Hold existing |

---

*All strategies tested. All rules enforceable. All emotion removed.*
