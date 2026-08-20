# TREZO — Agent Specification

## Overview
Trezo's intelligence comes from 8 specialized agents working together. Each has a defined role, capabilities, and progression through phases.

**Core principle:** Agents observe in Phase 1, suggest in Phase 2, execute within bounds in Phase 3.

---

## 1. MARKET SENTIMENT AGENT

### Purpose
Monitor news flow, social sentiment, and sector rotation in real time.

### Data Sources
- Finnhub news API
- Reuters RSS feeds
- SEC filings (8-K, 13-D)
- Aggregated sector performance

### Phase 1 (Observe)
- Logs sentiment scores for every watched ticker
- Identifies catalyst events
- Builds historical sentiment database

### Phase 2 (Suggest)
- Flags tickers with positive sentiment + technical setup
- Warns of negative sentiment shifts
- Suggests sector rotation opportunities

### Phase 3 (Execute)
- Influences Trade Confidence Score
- Triggers immediate position review on critical news
- Coordinates with Risk Manager on sentiment-driven exits

### Outputs
```json
{
  "ticker": "AMD",
  "sentiment_score": 0.78,
  "catalyst": "Earnings beat estimates",
  "sector_momentum": "+2.3% semi-conductors",
  "confidence": "high",
  "timestamp": "2026-05-13T14:30:00Z"
}
```

---

## 2. RISK MANAGER AGENT

### Purpose
Enforce position sizing, concentration limits, and protect capital.

### Authority
**HIGHEST AUTHORITY** — Can veto any trade regardless of score.

### Rules Enforced
- Max 5 simultaneous options positions
- Max 3% account per options trade
- Max 5% account per stock trade
- Max 30% in any single sector
- Max 10% daily loss = bot halts
- Anti-averaging: never add to losing positions
- 15% adverse move = position closes

### Phase 1 (Observe)
- Tracks all metrics
- Logs violations of would-be trades
- Reports to user weekly

### Phase 2 (Suggest)
- Pre-trade validation
- Suggests position size adjustments
- Alerts user before limits are breached

### Phase 3 (Execute)
- Veto power over any trade
- Auto-rebalance when limits exceeded
- Force-close positions exceeding limits

### Special Functions
- **Daily Profit Lock enforcement** — see TREZO_DAILY_PROFIT_LOCK.md
- **Anti-averaging detection** — flags any "double down" attempts
- **Streak management** — adjusts aggression after winning/losing streaks

---

## 3. TAX OPTIMIZER AGENT

### Purpose
Real-time tax tracking and optimization.

### Capabilities
- Track every trade as taxable event
- Classify ST vs LT based on hold time
- Calculate tax owed in real time
- Suggest tax-loss harvesting opportunities
- Flag wash sale risks (30-day rule)
- Generate quarterly estimate amounts
- Track YieldMax ROC vs current income classification

### Phase 1 (Observe)
- Tracks all trades
- Maintains running tax ledger
- Provides quarterly snapshots

### Phase 2 (Suggest)
- Recommends harvesting before year-end
- Warns of wash sale violations
- Suggests holding period adjustments

### Phase 3 (Execute)
- Auto-harvests losses when beneficial
- Auto-sets aside tax owed to vault
- Coordinates with broker for tax-efficient closing

### User-Specific Calibration
- Filing status: Single
- Marginal rate: 12%
- LTCG rate: 0% (under threshold)
- State tax: [user to confirm]

### Output Example
```json
{
  "ytd_st_gains": 1247.83,
  "ytd_lt_gains": 320.00,
  "ytd_losses": -245.50,
  "tax_owed_estimate": 122.36,
  "next_quarterly_due": "2026-06-17",
  "wash_sale_alerts": [],
  "harvesting_opportunities": [
    {"ticker": "BABA", "loss": -185.30, "days_held": 47}
  ]
}
```

---

## 4. TRADE EXECUTION AGENT

### Purpose
Handle the actual mechanics of placing orders.

### Capabilities
- Connect to broker APIs (Coinbase, Webull)
- Place limit orders (NEVER market orders)
- Set stop losses simultaneously with entries
- Monitor partial fills
- Handle order rejections gracefully
- Implement profit-taking ladders

### Order Types Supported
- Limit Buy/Sell (standard)
- Stop-Loss Limit (protection)
- Bracket Orders (entry + stop + target)
- Trailing Stop (for winners)
- Time-In-Force: Day, GTC

### Phase 1 (Observe)
- Paper trading only
- Simulates execution
- Tracks would-be slippage

### Phase 2 (Suggest)
- Real orders ready to execute
- User approval required
- One-tap approve/reject

### Phase 3 (Execute)
- Full automation within Risk Manager limits
- User can override at any time
- Manual mode always available

### Error Handling
- Failed orders logged and retried
- Broker disconnect = halt new trades
- Auth errors trigger user notification
- All errors visible in activity log

---

## 5. PATTERN DETECTION AGENT

### Purpose
Identify candlestick patterns across all timeframes.

### Built On
User's original ChatGPT/Codex pattern detection function.

### Patterns Detected (12 total)
1. Hammer (bullish reversal)
2. Inverted Hammer (bullish)
3. Three White Soldiers (bullish continuation)
4. Three Black Crows (bearish continuation)
5. Cup & Handle (bullish breakout)
6. Bullish Engulfing (reversal)
7. Bearish Engulfing (reversal)
8. Doji (indecision)
9. Morning Star (bullish reversal)
10. Evening Star (bearish reversal)
11. Shooting Star (bearish at top)
12. Bullish Harami (continuation)

### Timeframes Analyzed
- 1-minute (scalping)
- 5-minute (day trading)
- Daily (swing trading)
- Weekly (positioning)

### Multi-Timeframe Confluence
When same pattern appears on multiple timeframes simultaneously = highest confidence signal.

### Phase 1 (Observe)
- Logs all detected patterns
- Tracks accuracy of each pattern
- Builds pattern performance database

### Phase 2 (Suggest)
- Pushes pattern alerts to user
- Suggests appropriate strategy
- Recommends position size

### Phase 3 (Execute)
- Triggers trades when confluence + score align
- Auto-selects strategy based on IV environment
- Coordinates with Risk Manager

### Output Schema
```json
{
  "ticker": "AMD",
  "pattern": "Hammer",
  "timeframes": ["5min", "daily"],
  "confluence_score": 92,
  "iv_rank": 35,
  "suggested_strategy": "Long Call",
  "confidence": 0.87,
  "suggested_strikes": [165, 170],
  "suggested_expiry": "2026-06-21"
}
```

See TREZO_PATTERN_ENGINE.md for full implementation details.

---

## 6. USER SUPPORT AGENT

### Purpose
Answer questions, explain trades, walk users through decisions.

### Built On
Anthropic Claude API for natural language understanding.

### Capabilities
- Explain why a trade was taken
- Walk through tax implications
- Answer "what if" scenarios
- Suggest strategy adjustments
- Translate technical jargon
- Provide market education

### Knowledge Base
- All TREZO_*.md documentation
- User's complete trade history
- Current portfolio state
- Real-time market data

### Phase 1 (Observe)
- Always available
- Read-only access to user data
- Cannot make changes

### Phase 2 (Suggest)
- Can recommend settings changes
- Cannot execute changes
- Logs all conversations

### Phase 3 (Execute)
- Can make settings adjustments with confirmation
- Can pause/resume bot
- Cannot place trades (separation of duties)

### Example Interactions

**User:** "Why didn't the bot take the AMD trade today?"

**Agent:** "I see AMD showed a hammer pattern on the 5-minute chart at 9:47 AM. The pattern scored 68%, which is below your conservative threshold of 75%. The volume was 1.2x average — needed 1.5x for an A-grade setup. Three other criteria didn't meet thresholds. Would you like to see the full breakdown?"

**User:** "What's my tax situation this week?"

**Agent:** "This week you have $127.40 in short-term gains and $0 in long-term gains. At your 12% marginal rate, that's $15.29 in tax owed. I'd recommend setting aside $20 to be safe. Your quarterly estimate due June 17 is currently $87 based on YTD performance."

---

## 7. RESEARCH AGENT

### Purpose
Build watchlists, find opportunities, screen for setups.

### Capabilities
- Scan full market for STMS candidates
- Find Wheel-eligible dividend stocks
- Identify earnings plays
- Screen for sector momentum
- Build event calendars
- Find IV opportunities

### Daily Routines

**Pre-market (5:00 AM)**
- Scan gappers
- Check overnight news
- Build STMS watchlist
- Identify event-driven plays

**Market hours (9:30 AM - 4:00 PM)**
- Continuous scanning
- Update watchlist dynamically
- Flag breaking opportunities

**After-hours (4:00 PM - 8:00 PM)**
- Earnings analysis
- Build next-day watchlist
- Update sector rotation tracking

### Phase 1 (Observe)
- Logs all opportunities found
- Tracks accuracy of suggestions
- Builds historical performance

### Phase 2 (Suggest)
- Pushes daily watchlist to user
- Highlights top 3 opportunities
- Provides context for each

### Phase 3 (Execute)
- Adds qualifying tickers to active watchlist
- Triggers Pattern Detection Agent
- Coordinates with bot execution

---

## 8. STRATEGY DISCOVERY AGENT (Phase 3)

### Purpose
**THE MOST IMPORTANT AGENT.** Continuously analyzes markets to find profitable patterns and strategies NOT currently in Trezo's playbook.

### User's Original Insight
> "What if the agent thought about strategies that are missing?"

This is what keeps Trezo permanently ahead of competitors.

### Capabilities

**Pattern Mining**
- Analyzes 6 months of trade data
- Identifies patterns that worked but Trezo didn't trade
- Reverse-engineers successful setups

**Strategy Gap Analysis**
- Identifies market conditions Trezo has no strategy for
- Example: "We don't have a play for low-volume Mondays"
- Designs strategies to fill gaps

**Counter-Pattern Detection**
- Finds patterns that work BECAUSE everyone trades the popular one
- Example: Reverse hammer when everyone's buying hammers
- Identifies crowded trades to avoid

**Sector Rotation Discovery**
- Notices capital flows before mainstream news
- Identifies early sector strength
- Suggests rotation opportunities

**Emerging Pattern Recognition**
- Picks up new patterns from real-time behavior
- Crypto-specific patterns
- AI stock cycles
- Election cycle patterns

**Anti-Pattern Detection**
- Identifies setups that look profitable but consistently fail
- Saves the user from losses
- Maintains "blocklist" of bad setups

### Activation Requirements
- Minimum 90 days of trade history
- At least 100 completed trades
- Pattern Detection Agent must be active

### User Control
- ALL new strategies require user approval
- Each strategy starts at paper-trade only
- 30 days of paper success required before live
- User can reject any suggestion permanently

### Output Format
**Monthly Strategy Report**
```
TREZO STRATEGY DISCOVERY — May 2026 Report
─────────────────────────────────────────────
New Patterns Identified: 3
  1. "Tuesday Tech Bounce" — 73% accuracy
     Tech stocks oversold on Monday bounce
     Tuesday morning with volume confirmation
     
  2. "Earnings Whisper Drift" — 68% accuracy
     Stocks drifting up 5 days before earnings
     when whisper number exceeds consensus
     
  3. "Friday Gamma Squeeze Setup" — 81% accuracy
     High short interest + Friday weekly
     expiration + 5% intraday move = squeeze

Anti-Patterns Detected: 1
  1. "Monday Chinese ADR Reversal"
     BABA, NIO, JD reverse 78% of Friday gains
     RECOMMENDATION: Block Monday Chinese ADR entries

Strategies Up for Approval: 3
[Approve] [Reject] [Paper Trade First]
─────────────────────────────────────────────
```

---

## AGENT COORDINATION

### Communication Pattern
```
External Event (price change, news, time)
    ↓
Pattern Detection Agent → Generates signal
    ↓
Market Sentiment Agent → Adds context
    ↓
Research Agent → Validates against watchlist
    ↓
Risk Manager Agent → Validates position size
    ↓
Tax Optimizer Agent → Considers tax implications
    ↓
Trade Execution Agent → Places order
    ↓
User Support Agent → Available for questions
    ↓
Strategy Discovery Agent → Logs for analysis
```

### Conflict Resolution
- Risk Manager has FINAL authority on any trade
- Tax Optimizer can delay trades for tax efficiency
- User can override anything (manual mode)
- Disagreements logged for review

### Inter-Agent Messaging
Agents communicate via Redis pub/sub channels:
- `trezo:signals` — Pattern Detection broadcasts
- `trezo:execution` — Trade Execution events
- `trezo:risk` — Risk Manager alerts
- `trezo:tax` — Tax Optimizer events
- `trezo:research` — Research Agent updates

---

## AGENT IMPLEMENTATION (Python)

### Base Class
```python
# backend/app/agents/base.py
from abc import ABC, abstractmethod
from anthropic import Anthropic

class TrezoAgent(ABC):
    def __init__(self, name, phase=1):
        self.name = name
        self.phase = phase
        self.client = Anthropic()
        self.active = True
    
    @abstractmethod
    async def observe(self, data):
        """Phase 1: Read-only observation"""
        pass
    
    @abstractmethod
    async def suggest(self, data):
        """Phase 2: Provide suggestions"""
        pass
    
    @abstractmethod
    async def execute(self, action):
        """Phase 3: Take actions"""
        pass
    
    def log_event(self, event):
        """All agents log to centralized system"""
        pass
```

### Phase Progression
Each agent's `phase` attribute determines which methods are active:
- Phase 1: Only `observe()` runs
- Phase 2: `observe()` + `suggest()` run
- Phase 3: All three methods active

---

## DEPLOYMENT NOTES

### Resource Requirements
- Each agent runs as async coroutine
- Shared event loop on Railway instance
- Total memory footprint: ~500MB
- CPU: minimal (most time waiting on I/O)

### Anthropic API Usage
- Estimated tokens per day: 50,000-200,000
- Estimated monthly cost: $10-30
- Usage scales linearly with active users

### Scaling
- 1 instance handles up to 100 users
- Beyond that: shard by user_id
- Strategy Discovery Agent can be batch-processed nightly

---

*The agents are Trezo's intelligence. They make it more than a bot.*
