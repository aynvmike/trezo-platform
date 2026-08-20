# TREZO — CREDIT SPREADS STRATEGY

## Purpose
A defined-risk, defined-reward income strategy that fits perfectly inside the Woven Basket. Credit spreads compound small accounts faster than directional options while keeping losses capped. This is a major addition to Layer 3 (Options Engine) and supports Layer 4 (Dividend Wheel).

---

## CORE PHILOSOPHY

> **"Never risk more than you can make."**

Credit spreads are the founder's preferred path for consistent monthly income because:
1. **Losses are defined** — bought leg caps the downside
2. **Profits are immediate** — credit hits account at entry
3. **Theta works for you** — time decay = profit
4. **High win rate possible** — 70-80% probability with conservative deltas
5. **Compounds small accounts** — 18-25% return per spread in 23-30 days

---

## STRATEGY OVERVIEW

### Three Spread Types

**1. Put Credit Spread (Bullish)**
- Sell a put closer to current price
- Buy a put further below
- Collect net credit
- Win if stock stays above short strike

**2. Call Credit Spread (Bearish)**
- Sell a call closer to current price
- Buy a call further above
- Collect net credit
- Win if stock stays below short strike

**3. Iron Condor (Neutral)**
- Combine put credit spread + call credit spread on same underlying
- Win if stock stays between both short strikes
- Higher profit potential, but both sides have risk

---

## ENTRY RULES

### Rule 1: Days to Expiration (DTE)
**Target: 30-40 DTE**

Theta decay accelerates dramatically in this window. Premium decays faster than further-dated contracts, maximizing time-efficient income.

```
THETA DECAY ZONE:
─────────────────────────────────────────────
70+ DTE: Premium decays slowly. Wasted time.
45-50 DTE: Decay starts accelerating.
30-40 DTE: ★ SWEET SPOT ★ Max theta efficiency.
14-21 DTE: Decay is fast, but gamma risk rises.
< 7 DTE: Gamma risk too high. Avoid.
─────────────────────────────────────────────
```

**Trezo Bot Rule:** Open spreads only when 30-40 DTE available. If only 25 DTE, wait for next cycle.

### Rule 2: Probability of Profit (POP) / Delta
**Target: 70-80% POP**

This corresponds to approximately a 0.20-0.30 delta on the short leg. Statistically, this represents one standard deviation in a normal distribution — a conservative starting point.

```
POP TARGETING:
─────────────────────────────────────────────
60% POP: Too aggressive. Higher credit, but loss frequency too high.
70-75% POP: ★ BEGINNER SWEET SPOT ★
75-80% POP: Conservative, lower credit but high win rate.
85%+ POP: Too far OTM. Credit too small to justify.
─────────────────────────────────────────────
```

**Trezo Bot Rule:** Short leg must have delta between 0.20 and 0.30. Outside this range, no trade.

### Rule 3: Width Between Strikes
**Target: 5-point width (narrowest available)**

Wider spreads collect more credit but worse return on risk. Narrow spreads compound faster.

```
WIDTH ANALYSIS (Example: MSFT 30 DTE):
─────────────────────────────────────────────
5-point width:  $76 credit / $422 risk = 18% ROI
10-point width: $104 credit / $896 risk = 11.6% ROI
20-point width: $145 credit / $1,855 risk = 7.8% ROI

WINNER: 5-point width. Sell 2x 5-point > 1x 10-point.
─────────────────────────────────────────────
```

**Trezo Bot Rule:** Always use the narrowest available width on the underlying. Multiple narrow spreads beat one wide spread.

### Rule 4: Underlying Stock Selection
**Target: Predictable stocks with clean moving averages**

The single biggest predictor of credit spread success is choosing the right underlying.

**APPROVED STOCK CRITERIA:**
- Liquid options market (open interest > 500 per strike)
- Daily volume > 1M shares
- Implied volatility above 25% (need enough premium)
- **Clean moving averages** — 20/50/200 SMA slopes don't whipsaw
- Predictable trend (uptrend or downtrend, not chop)
- No earnings within DTE window

**APPROVED LIST (calibrated to founder's history):**
| Ticker | Why |
|---|---|
| MSFT | Stable mega-cap, clean trend |
| LMT | Predictable defense play |
| UNH | Stable healthcare (note: avoid during controversies) |
| TSM | Semiconductor with clean trend |
| WMT | Founder's top winner, stable retail |
| INTC | Founder's winner, semis |
| AMD | Volatile but founder has edge here |
| CSCO | Stable mid-cap tech |
| MRK | Pharma stability |
| GM | Auto with clean trends |

**AVOID FOR CREDIT SPREADS:**
| Ticker | Why |
|---|---|
| TSLA | Too volatile, whipsaws moving averages |
| Penny stocks | Insufficient liquidity |
| AI hype names | Volatility crushes risk/reward |
| Chinese ADRs | Regulatory risk |
| Pre/post earnings | Vol crush risk |

### Rule 5: Implied Volatility (IV) Timing
**Target: Enter when IV is elevated, exit when IV drops**

Higher IV = higher premium = more credit. The bot watches for IV spikes (often from market fear or earnings runs nearby) and enters spreads when premium is rich.

**Trezo Bot Rule:** Pattern Detection Agent feeds IV rank to Strategy Engine. Spreads entered at IV rank > 40 get preference.

---

## EXIT RULES

### The Dynamic Stop Loss System

This is the **most important rule** in credit spreads. Most beginners lose because they let a winning trade become a losing trade.

```
DYNAMIC STOP LOSS PROGRESSION
─────────────────────────────────────────────
ENTRY:
  Initial stop = 100% of credit collected
  (Risk no more than what you collected)
  
50% PROFIT REACHED:
  → Move stop UP to break-even
  (Lock in: no loss possible from here)
  
75% PROFIT REACHED:
  → Move stop UP to 50% profit lock
  (Guaranteed minimum: 50% of credit)
  
87.5% PROFIT REACHED:
  → Move stop UP to 75% profit lock
  (Guaranteed minimum: 75% of credit)
  
EXIT TRIGGERS:
  - Stop loss hit (close at current level)
  - 21 DTE remaining (close before gamma risk)
  - Earnings announcement scheduled (close 1 day prior)
─────────────────────────────────────────────
```

**Example walkthrough:**

```
Day 0: Sell MSFT 505/500 put credit spread
       Credit collected: $120
       Initial stop: $120 loss (spread worth $240)
       Target: $0 (spread worth $0 at expiration)

Day 10: Spread now worth $60 (50% profit)
        → Move stop to break-even ($120 spread)
        → Worst case from here: $0 profit, no loss

Day 18: Spread now worth $30 (75% profit)
        → Move stop to $60 (50% profit lock)
        → Guaranteed: minimum $60 profit

Day 22: Spread now worth $15 (87.5% profit)
        → Move stop to $30 (75% profit lock)
        → Guaranteed: minimum $90 profit

Day 25: Close at 90% profit ($108) before gamma risk
        → Final: +$108 (90% of max)
```

### Why This Works

The founder noted: *"Even when you win, save the minimum you want to make."* The Dynamic Stop Loss system is the credit spread version of this rule — once you're winning, lock in progressively more of the profit. The Daily Profit Lock vault catches it after the trade closes.

---

## RISK MANAGEMENT RULES

### Rule A: Never Risk More Than You Can Make
If credit collected is $100, maximum acceptable loss is $100. The bot closes any spread that drops to -100% of credit.

### Rule B: Position Sizing
- **Max 5 simultaneous spreads** (founder's concentration rule)
- **Max 3% of account per spread**
- **Max 30% of account in active spreads at any time**
- **Max 50% allocation to credit spreads strategy overall**

### Rule C: Anti-Averaging Rule
Never add to a losing spread. Never "roll for credit" if it increases risk.

### Rule D: Roll Rules
A spread can be rolled (closed and reopened further out) only if:
1. Current spread is profitable or breakeven
2. New spread collects net credit
3. New spread is on same underlying (no symbol change)
4. New DTE puts it back in 30-40 day window

---

## TRADE MANAGEMENT WORKFLOW

```
┌─────────────────────────────────────────────┐
│ DAILY CHECK (Bot, every market day)         │
├─────────────────────────────────────────────┤
│ For each open spread:                       │
│   1. Calculate current value                │
│   2. Compare to profit thresholds:          │
│      - 50%? → Raise stop to break-even      │
│      - 75%? → Raise stop to 50% lock        │
│      - 87.5%? → Raise stop to 75% lock      │
│   3. Check DTE:                             │
│      - 21 DTE? → Close position             │
│   4. Check upcoming earnings:               │
│      - < 2 days? → Close position           │
│   5. Check if stop hit:                     │
│      - Yes → Execute close order            │
│                                             │
│ NEW ENTRY SCAN:                             │
│   1. Pattern Detection identifies setup     │
│   2. Verify: 30-40 DTE available            │
│   3. Verify: Stock on approved list         │
│   4. Verify: Clean moving averages          │
│   5. Calculate optimal strikes (0.20-0.30Δ) │
│   6. Confirm minimum credit threshold       │
│   7. Submit order with all rules tagged     │
└─────────────────────────────────────────────┘
```

---

## INTEGRATION WITH TREZO LAYERS

### Layer 3 (Options Engine)
Credit spreads become **the primary strategy** for the Options Engine after Phase 6 (paper trading validation). They replace many of the directional options trades the founder has historically taken that lost money.

### Layer 4 (Dividend Wheel)
Cash-secured puts (the foundation of the wheel) are functionally **naked put credit spreads with no long leg**. The bot can convert any wheel CSP into a credit spread by adding a protective long put, reducing capital required.

### Layer 6 (Tax Optimizer)
Credit spreads expire weekly/monthly, generating frequent short-term capital gains. Tax Optimizer Agent tracks them separately and projects quarterly estimated tax payments.

### Pattern Detection Agent
The Agent's job for credit spreads is different than directional options:
- For directional trades: predict direction (bullish/bearish signal)
- For credit spreads: predict **lack of movement** (will stock stay in range?)

This requires different signals:
- Low ATR (Average True Range)
- Tight Bollinger Bands
- IV rank elevated but not extreme
- Stock between support and resistance
- No catalysts in DTE window

---

## TRACKING METRICS

Every credit spread trade tracks:

| Metric | Definition | Target |
|---|---|---|
| Win rate | % of spreads that close profitable | 75%+ |
| Average win | Average dollar profit per winning spread | Track baseline |
| Average loss | Average dollar loss per losing spread | < avg win |
| Capture rate | % of max profit captured | 85%+ |
| Profit factor | Total wins / total losses | > 2.0 |
| Avg DTE held | Days from entry to exit | 18-22 days |
| Profit/risk | Avg profit / avg risk per spread | 25%+ |

The founder's reference data from the source document:
- Win rate: 94% (one loss out of many)
- Average win: $2,600
- Average loss: $1,900 (less than avg win — the goal)
- Capture rate: 90%
- Profit/risk: 41%
- Average time in trade: 22 days

This is the **standard Trezo aspires to**.

---

## REAL-WORLD EXAMPLE (from source)

**LMT (Lockheed Martin) trade pattern:**

```
Setup observed: LMT bounced off 200-period SMA at $728
Action: Sold weekly/biweekly put credit spreads as it trended up
Approach: Continued selling spreads each week the trend held
Total realized: ~$12,000 over the trend window
Loss tolerance: Accepted occasional $1,500-$2,000 losses
                when 50% stop hit during pullbacks
Net result: Highly profitable swing of credit spread sales
```

This is the playbook. **Find predictable stocks → sell spreads on the trend → cut losses fast → let winners run.**

---

## COMMON MISTAKES TO AVOID

| Mistake | Consequence | Trezo Rule |
|---|---|---|
| Trading volatile stocks (TSLA, meme stocks) | Whipsaws stop you out | Approved list only |
| Selling too far OTM (90%+ POP) | Credit too small | 70-80% POP enforced |
| Wide spreads (20+ point) | Poor ROI | 5-point width preferred |
| Not setting stops | Catastrophic losses | Stops mandatory at entry |
| Holding to expiration | Gamma risk | Close at 21 DTE |
| Trading through earnings | IV crush losses | Skip earnings windows |
| Averaging losers | Compounds losses | Hard-blocked by bot |
| Letting winner become loser | Psychological damage | Dynamic stops enforced |

---

## EDUCATIONAL NOTES FOR USER

Credit spreads require understanding of:

1. **Options pricing** — How premium is calculated (intrinsic + extrinsic value)
2. **The Greeks** — Especially delta and theta
3. **Probability of Profit** — Statistical interpretation
4. **Margin requirements** — Spreads require margin, not cash
5. **Assignment risk** — What happens if short leg goes ITM

Trezo's User Support Agent will explain each concept when the user encounters it for the first time. Educational tooltips throughout the credit spreads UI.

---

## BUILDOUT PRIORITY

This strategy goes into **Phase 6 (Paper Trading)** initially. After 30+ consecutive paper trades with results matching the 75%+ win rate target, it graduates to real money in Phase 9.

In Phase 10 (Strategy Discovery), the Agent will analyze which specific stocks and setups within credit spreads have been most profitable for THIS user, and prioritize those.

---

## END OF CREDIT SPREADS STRATEGY SPEC
