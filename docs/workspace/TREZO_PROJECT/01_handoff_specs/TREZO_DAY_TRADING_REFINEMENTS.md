# TREZO — DAY TRADING REFINEMENTS

## Purpose
This document captures refinements to the Pattern Detection Engine and STMS (Small Trades Momentum Strategy) based on the founder's day trading study materials. These are upgrades to the existing `TREZO_PATTERN_ENGINE.md` and `TREZO_STRATEGY_RULES.md` specifications.

---

## THE "TWO YES" RULE — Confluence Required

The most critical refinement from the day trading guide: **two independent indicators must both signal positive for a trade to fire.**

> *"One no means no. They both have to say yes for me to take a trade."*

### The Two Indicators

**1. MACD (Moving Average Convergence Divergence)**
- Must be positive (above zero line)
- Must be opening / expanding (not flat or compressing)
- Histogram increasing preferred

**2. Volume**
- Must be elevated relative to average (1.5x+ average volume)
- Must be on green candles (buying pressure, not selling)
- Light selling volume = acceptable
- Heavy selling volume = automatic NO

### Trezo Bot Logic

```python
def confluence_check(symbol: str, timeframe: str = "5m") -> bool:
    """
    Returns True only if BOTH MACD and Volume signal positive.
    Returns False if either says NO.
    """
    macd_signal = check_macd(symbol, timeframe)
    volume_signal = check_volume(symbol, timeframe)
    
    if macd_signal == "NO":
        return False
    
    if volume_signal == "NO":
        return False
    
    return macd_signal == "YES" and volume_signal == "YES"
```

This logic is hard-coded into the Pattern Detection Agent. Without confluence, no trade signal fires regardless of candlestick pattern quality.

---

## TRADE SETUP REFINEMENTS

### The Setup Trezo Will Trade

Based on the day trading guide methodology, this is the canonical setup for STMS:

```
SETUP CHECKLIST (all must be true):
─────────────────────────────────────────────
□ Stock priced $2-$20 (small/mid-cap range)
□ Pre-market gapped up 5%+
□ News catalyst identified (earnings, FDA, etc.)
□ Relative volume > 2x average
□ Float < 50 million shares (smaller = better)
□ Clean technical pattern (flag, breakout, hammer)
□ MACD positive and opening
□ Volume confirmation on green candles
□ First candle makes new high above previous
─────────────────────────────────────────────
ENTRY: First candle that breaks above prior high
STOP: Below recent low (typically 5-8% away)
TARGET 1: 1x risk (close 1/3)
TARGET 2: 2x risk (close 1/3)
TARGET 3: 3x risk (let final 1/3 run)
TIME STOP: Close all by 11:00 AM ET regardless
─────────────────────────────────────────────
```

### The Setup Trezo Will NOT Trade

```
AUTOMATIC DISQUALIFIERS:
─────────────────────────────────────────────
✗ MACD flat or negative
✗ High volume selling (red candles dominate)
✗ Wide spreads (>2% bid-ask gap)
✗ Float > 100M (too much resistance)
✗ Stock priced > $50 (outside STMS zone)
✗ No clear catalyst
✗ Already up 50%+ on the day (extended)
✗ After 11:00 AM (outside STMS window)
─────────────────────────────────────────────
```

---

## RISK MANAGEMENT RULES (from the guide)

### Cardinal Rules

1. **Cut losses quickly** — A losing trade should close at -5% to -8% maximum
2. **No revenge trading** — One loss does not authorize a bigger next trade
3. **Daily loss limit** — Stop trading for the day after 2 consecutive losses
4. **Risk/reward minimum 1:2** — Never risk $100 to make less than $200
5. **Don't trade without a strategy** — Random trades are tuition payments
6. **Win rate target** — 60-70% with proper R:R = profitable system

### Trezo Implementation

```
DAILY CIRCUIT BREAKERS:
─────────────────────────────────────────────
After 2 consecutive losing trades:
  → Bot pauses for remainder of session
  → User notified with explanation
  → Trading resumes next session

After 3% account drawdown in single day:
  → All open positions close at market
  → Bot disables for 24 hours
  → Mandatory user review before re-enabling

After 10% account drawdown in single week:
  → Bot disables entirely
  → Requires user manual override + new risk settings
─────────────────────────────────────────────
```

---

## TRADER PSYCHOLOGY (Integrated Into Bot Design)

The day trading guide emphasizes psychology as the difference between profitable and unprofitable traders. Trezo's design reflects this by **removing the psychological burden from the user.**

### Common Psychological Mistakes (and Trezo's Solution)

| Psychological Mistake | Trezo's Solution |
|---|---|
| FOMO entries (chasing) | Bot only enters on its rule set |
| Holding losers hoping | Hard stops, no overrides |
| Cutting winners early | Profit targets enforced |
| Revenge trading after loss | Circuit breaker pauses bot |
| Overtrading | Position count cap (max 5) |
| Increasing size after loss | Position size fixed |
| Trading tilted/emotional | Bot doesn't have emotions |

### The Discipline Triggers (from the guide)

Per the source: *"Take notes on potential triggers that cause you to become emotional. Develop a list of triggers to be on the lookout for and to stop trading the moment they occur."*

Trezo's user dashboard includes a **Trigger Awareness section** where the user can log emotional states:
- Sleep < 6 hours? → Bot conservatism mode
- Personal stress event? → Bot pause option
- Recent big loss? → Bot reduces position size automatically
- Big win euphoria? → Bot prevents oversized next entry

---

## STOCK SELECTION CRITERIA

The guide emphasizes that **trading the right stock is more important than trading the right setup.**

### STMS Stock Universe (Updated)

```
DAILY SCAN CRITERIA:
─────────────────────────────────────────────
PRICE RANGE: $1.00 - $20.00
DAILY VOLUME: > 500K minimum, prefer > 2M
RELATIVE VOLUME: > 2x average
PRE-MARKET MOVE: 5%+ gap
FLOAT: < 50M preferred, < 100M acceptable
NEWS CATALYST: Required
                (earnings, FDA, partnerships,
                 merger, sector news)
EXCHANGE: NYSE, NASDAQ only (no OTC)
SPREAD: < 2% bid-ask
─────────────────────────────────────────────
```

### Catalysts to Watch For

| Catalyst | Reliability | Notes |
|---|---|---|
| Earnings beat | High | Often gap-and-go |
| FDA approval | High | Biotech specialty |
| Buyout/merger news | Highest | Watch for confirmation |
| Insider buying | Medium | Form 4 filings |
| Analyst upgrade | Medium | Often fades |
| Sector momentum | Medium | Sympathy plays |
| Social media buzz | Low | Avoid pure pump |
| Earnings miss bounce | Low | Counter-trend, risky |

---

## TIME-OF-DAY RULES

### The STMS Window

```
TRADING SCHEDULE (Eastern Time):
─────────────────────────────────────────────
4:00 AM - 9:30 AM: Pre-market analysis
  → Scan gappers
  → Identify catalysts
  → Build watchlist
  → Set alerts

9:30 AM - 10:30 AM: PRIMARY TRADING WINDOW
  → Highest volume + volatility
  → 60-70% of daily moves happen here
  → Bot most active

10:30 AM - 11:00 AM: WINDING DOWN
  → New entries discouraged
  → Manage open positions
  → Trail stops aggressively

11:00 AM: HARD STOP
  → All STMS positions close
  → Bot transitions to swing/options layers

11:00 AM - 4:00 PM: SWING/OPTIONS MANAGEMENT
  → No new STMS trades
  → Options entries possible
  → YieldMax monitoring

4:00 PM - 8:00 PM: POST-MARKET
  → Earnings reviews
  → Next day prep
─────────────────────────────────────────────
```

---

## INDICATOR SETTINGS (Standardized)

To ensure consistency, all Trezo charts use:

| Indicator | Setting | Purpose |
|---|---|---|
| MACD | 12, 26, 9 | Trend + momentum |
| RSI | 14-period | Overbought/oversold |
| Volume MA | 20-period | Volume normalization |
| SMA Fast | 9-period | Short-term trend |
| SMA Medium | 20-period | Medium-term trend |
| SMA Long | 50-period | Major trend |
| SMA Major | 200-period | Long-term trend |
| VWAP | Daily | Institutional bias |
| ATR | 14-period | Volatility / stop sizing |
| Bollinger Bands | 20, 2σ | Range identification |

---

## BACKTESTING REQUIREMENTS

Before any STMS variant goes live, the bot must demonstrate:

- Minimum 100 paper trades
- Win rate > 55%
- Average R:R > 1.5
- Maximum drawdown < 15%
- Profit factor > 1.5
- Recovery time after drawdown < 5 trades

If any metric fails, the strategy returns to development.

---

## RELATIONSHIP TO PATTERN ENGINE

This document **extends** TREZO_PATTERN_ENGINE.md with day trading specific rules. The core pattern detection (hammers, engulfing, etc.) remains as specified there. This document adds:

1. **Confluence requirement** (MACD + Volume must agree)
2. **Time-of-day filter** (STMS window enforcement)
3. **Stock universe filters** (price, volume, float, catalyst)
4. **Psychological circuit breakers** (loss limits, cooling-off periods)
5. **R:R targeting** (1:2 minimum, 1:3 preferred)

---

## INTEGRATION CHECKLIST FOR CLAUDE CODE

When implementing these refinements:

- [ ] Add MACD calculation to Pattern Engine
- [ ] Add Volume analysis to Pattern Engine
- [ ] Implement confluence_check() function
- [ ] Add STMS time window enforcement
- [ ] Build pre-market scanner with gap criteria
- [ ] Build catalyst news aggregator (Finnhub news)
- [ ] Implement daily circuit breakers (loss limits)
- [ ] Add R:R calculator at trade entry
- [ ] Add scaled exit system (1/3, 1/3, 1/3)
- [ ] Build time-stop enforcement (11:00 AM hard stop)
- [ ] Add Trigger Awareness panel to UI

---

## END OF DAY TRADING REFINEMENTS
