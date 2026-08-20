# TREZO — Pattern Detection Engine

## Origin
This pattern detection engine is built on the foundation of the user's original ChatGPT/Codex function. The user's logic was production-ready and saved approximately 2 weeks of development time.

## Founder's Original Code

```javascript
// User's original ChatGPT/Codex implementation
// This is the seed of Trezo's Pattern Detection Agent

function isHammer(c) {
  const body = Math.abs(c.close - c.open);
  const range = c.high - c.low;
  const lowerWick = Math.min(c.open, c.close) - c.low;
  const upperWick = c.high - Math.max(c.open, c.close);

  return (
    range > 0 &&
    body / range < 0.35 &&
    lowerWick >= body * 2 &&
    upperWick <= body
  );
}

// Multi-factor scoring (founder's original)
const criteria = {
  trend: price > ema20 && ema20 > ema50,
  momentum: rsi14 > 50 && rsi14 < 70,
  macd: macd.hist > 0 && macd.macd > macd.signal,
  volume: currentVolume > avgVolume20 * 1.5,
  breakout: close > highestHigh(candles.slice(-20)),
  candle: isBullishEngulfing(prev, current) || isHammer(current)
};

let score = 0;
if (criteria.trend) score += 20;
if (criteria.momentum) score += 15;
if (criteria.macd) score += 20;
if (criteria.volume) score += 15;
if (criteria.breakout) score += 20;
if (criteria.candle) score += 10;

const alert = score >= 70;
```

**This is the foundation. We build on it.**

---

## 1. EXPANDED PATTERN LIBRARY (12 PATTERNS)

### Bullish Patterns

**1. Hammer** (founder's original)
```python
def is_hammer(candle):
    body = abs(candle.close - candle.open)
    range_ = candle.high - candle.low
    lower_wick = min(candle.open, candle.close) - candle.low
    upper_wick = candle.high - max(candle.open, candle.close)
    
    return (
        range_ > 0
        and body / range_ < 0.35
        and lower_wick >= body * 2
        and upper_wick <= body
    )
```

**2. Inverted Hammer** (NEW)
```python
def is_inverted_hammer(candle):
    body = abs(candle.close - candle.open)
    range_ = candle.high - candle.low
    upper_wick = candle.high - max(candle.open, candle.close)
    lower_wick = min(candle.open, candle.close) - candle.low
    
    return (
        range_ > 0
        and body / range_ < 0.35
        and upper_wick >= body * 2
        and lower_wick <= body
    )
```

**3. Three White Soldiers** (NEW)
```python
def is_three_white_soldiers(c1, c2, c3):
    """Three consecutive bullish candles, each closing higher"""
    all_bullish = c1.close > c1.open and c2.close > c2.open and c3.close > c3.open
    progressive = c1.close < c2.close < c3.close
    similar_size = (
        abs((c2.close - c2.open) - (c1.close - c1.open)) / (c1.close - c1.open) < 0.5
    )
    no_long_wicks = all(
        (c.high - max(c.open, c.close)) < (c.close - c.open) * 0.3 
        for c in [c1, c2, c3]
    )
    return all_bullish and progressive and similar_size and no_long_wicks
```

**4. Bullish Engulfing** (NEW)
```python
def is_bullish_engulfing(prev, current):
    prev_bearish = prev.close < prev.open
    current_bullish = current.close > current.open
    engulfs = current.open < prev.close and current.close > prev.open
    return prev_bearish and current_bullish and engulfs
```

**5. Morning Star** (NEW)
```python
def is_morning_star(c1, c2, c3):
    """Bearish + small body + bullish reversal"""
    c1_bearish = c1.close < c1.open
    c2_small = abs(c2.close - c2.open) < (c1.open - c1.close) * 0.3
    c3_bullish = c3.close > c3.open
    c3_closes_high = c3.close > (c1.open + c1.close) / 2
    return c1_bearish and c2_small and c3_bullish and c3_closes_high
```

**6. Cup & Handle** (NEW - longer timeframe)
```python
def is_cup_and_handle(candles, lookback=40):
    """U-shaped recovery followed by small consolidation"""
    if len(candles) < lookback:
        return False
    
    midpoint = lookback // 2
    left = candles[:midpoint]
    right = candles[midpoint:]
    
    # Cup: starts high, dips, recovers
    cup_start = left[0].high
    cup_low = min(c.low for c in left + right[:midpoint//2])
    cup_end = right[-1].close
    
    cup_depth = (cup_start - cup_low) / cup_start
    recovery = (cup_end - cup_low) / (cup_start - cup_low)
    
    cup_valid = 0.10 < cup_depth < 0.50 and recovery > 0.85
    
    # Handle: small consolidation/pullback
    handle = candles[-5:]
    handle_range = (max(c.high for c in handle) - min(c.low for c in handle)) / handle[0].close
    handle_valid = handle_range < cup_depth * 0.3
    
    return cup_valid and handle_valid
```

**7. Bullish Harami** (NEW)
```python
def is_bullish_harami(prev, current):
    prev_bearish = prev.close < prev.open
    current_bullish = current.close > current.open
    inside_bar = (
        current.open > prev.close 
        and current.close < prev.open
        and current.high < prev.high
        and current.low > prev.low
    )
    return prev_bearish and current_bullish and inside_bar
```

### Bearish Patterns

**8. Three Black Crows**
```python
def is_three_black_crows(c1, c2, c3):
    """Mirror of Three White Soldiers"""
    all_bearish = c1.close < c1.open and c2.close < c2.open and c3.close < c3.open
    progressive = c1.close > c2.close > c3.close
    return all_bearish and progressive
```

**9. Bearish Engulfing**
```python
def is_bearish_engulfing(prev, current):
    prev_bullish = prev.close > prev.open
    current_bearish = current.close < current.open
    engulfs = current.open > prev.close and current.close < prev.open
    return prev_bullish and current_bearish and engulfs
```

**10. Evening Star**
```python
def is_evening_star(c1, c2, c3):
    """Mirror of Morning Star"""
    c1_bullish = c1.close > c1.open
    c2_small = abs(c2.close - c2.open) < (c1.close - c1.open) * 0.3
    c3_bearish = c3.close < c3.open
    c3_closes_low = c3.close < (c1.open + c1.close) / 2
    return c1_bullish and c2_small and c3_bearish and c3_closes_low
```

**11. Shooting Star**
```python
def is_shooting_star(candle):
    """Hammer inverted, at top of uptrend"""
    body = abs(candle.close - candle.open)
    range_ = candle.high - candle.low
    upper_wick = candle.high - max(candle.open, candle.close)
    
    return (
        range_ > 0
        and body / range_ < 0.30
        and upper_wick >= body * 2
        and candle.close < candle.open  # bearish body
    )
```

### Neutral Patterns

**12. Doji**
```python
def is_doji(candle):
    """Body is tiny vs range — indecision"""
    body = abs(candle.close - candle.open)
    range_ = candle.high - candle.low
    return range_ > 0 and body / range_ < 0.05
```

---

## 2. MULTI-TIMEFRAME CONFLUENCE

### The Power Concept
When the same pattern appears on multiple timeframes simultaneously, the signal strength multiplies. This is what professional traders call "confluence" and it's a major edge.

### Implementation
```python
async def detect_multi_timeframe_confluence(ticker):
    timeframes = ['1min', '5min', 'daily', 'weekly']
    detections = {}
    
    for tf in timeframes:
        candles = await fetch_candles(ticker, tf)
        detections[tf] = detect_all_patterns(candles)
    
    # Find patterns appearing on multiple timeframes
    confluence = {}
    all_patterns = set()
    for tf_patterns in detections.values():
        all_patterns.update(tf_patterns.keys())
    
    for pattern in all_patterns:
        timeframes_with_pattern = [
            tf for tf, patterns in detections.items() 
            if pattern in patterns
        ]
        if len(timeframes_with_pattern) >= 2:
            confluence[pattern] = {
                'timeframes': timeframes_with_pattern,
                'strength': calculate_confluence_strength(timeframes_with_pattern)
            }
    
    return confluence
```

### Confluence Scoring
- Pattern on 1 timeframe: Standard score
- Pattern on 2 timeframes: +30% to score
- Pattern on 3 timeframes: +60% to score
- Pattern on 4 timeframes: +100% (maximum signal)

---

## 3. ENHANCED 10-FACTOR SCORING

### Beyond Founder's Original 6 Criteria
Founder's code had 6 criteria totaling 100 points. Trezo expands to 10 criteria totaling 100 base + confluence bonus + catalyst bonus.

```python
def calculate_pattern_score(ticker, candles, market_data):
    score = 0
    breakdown = {}
    
    # Original 6 (preserved from founder's code)
    if criteria_trend(candles):
        score += 12  # Was 20, reduced to make room for new factors
        breakdown['trend'] = 12
    
    if criteria_momentum(candles):
        score += 10
        breakdown['momentum'] = 10
    
    if criteria_macd(candles):
        score += 12
        breakdown['macd'] = 12
    
    if criteria_volume(candles):
        score += 10
        breakdown['volume'] = 10
    
    if criteria_breakout(candles):
        score += 12
        breakdown['breakout'] = 12
    
    if criteria_candle_pattern(candles):
        score += 10
        breakdown['candle_pattern'] = 10
    
    # NEW factors
    if criteria_bb_position(candles):
        score += 8
        breakdown['bb_position'] = 8
    
    if criteria_vwap_alignment(candles):
        score += 8
        breakdown['vwap_alignment'] = 8
    
    if criteria_market_alignment(market_data):
        score += 8
        breakdown['market_alignment'] = 8
    
    if criteria_iv_environment(ticker):
        score += 10
        breakdown['iv_environment'] = 10
    
    # BONUS: Multi-timeframe confluence
    confluence = detect_multi_timeframe_confluence(ticker)
    if confluence:
        confluence_bonus = max(c['strength'] for c in confluence.values())
        score += confluence_bonus
        breakdown['confluence_bonus'] = confluence_bonus
    
    # BONUS: News catalyst
    catalyst = check_finnhub_news(ticker)
    if catalyst:
        score += 15
        breakdown['catalyst'] = 15
    
    return min(100, score), breakdown
```

---

## 4. SCALING TO TRADE CONFIDENCE SCORE (0-1000)

### The Multiplication Logic
Founder's score is 0-100. Trezo's Trade Confidence Score is 0-1000.

**Why 0-1000?**
- More granular (5 vs 50 = same difference proportionally)
- Allows for more nuanced thresholds
- Aligns with professional trading systems

### Scaling Formula
```python
def scale_to_trade_confidence(pattern_score, additional_factors):
    """
    pattern_score: 0-100 from pattern engine
    additional_factors: dict with options environment, risk/reward, etc.
    """
    # Pattern score becomes Technical Analysis component (300 max)
    technical_score = (pattern_score / 100) * 300
    
    # Add options environment (250 max)
    options_score = calculate_options_environment(additional_factors)
    
    # Add fundamental/event (200 max)
    fundamental_score = calculate_fundamental_score(additional_factors)
    
    # Add risk/reward (150 max)
    rr_score = calculate_risk_reward(additional_factors)
    
    # Add market conditions (100 max)
    market_score = calculate_market_conditions(additional_factors)
    
    total = technical_score + options_score + fundamental_score + rr_score + market_score
    return min(1000, int(total))
```

---

## 5. STRATEGY MAPPING

### Pattern → Strategy Auto-Selection

```python
PATTERN_STRATEGY_MAP = {
    'Hammer': {
        'high_iv': 'Long Call (short DTE)',
        'low_iv': 'Bull Call Spread',
        'wheel_stock': 'Cash-Secured Put'
    },
    'Inverted_Hammer': {
        'high_iv': 'Long Call',
        'low_iv': 'Bull Call Spread'
    },
    'Three_White_Soldiers': {
        'high_iv': 'Iron Condor (sell into strength)',
        'low_iv': 'Long Call or Debit Spread'
    },
    'Three_Black_Crows': {
        'high_iv': 'Bear Put Spread',
        'low_iv': 'Long Put'
    },
    'Cup_And_Handle': {
        'any_iv': 'Long Call 30-45 DTE'
    },
    'Bullish_Engulfing': {
        'high_iv': 'Bull Put Spread',
        'low_iv': 'Long Call'
    },
    'Doji_At_Resistance': {
        'any_iv': 'Iron Condor or Bear Spread'
    },
    'Shooting_Star': {
        'any_iv': 'Bear Put Spread'
    },
    'Bullish_Harami': {
        'high_iv': 'Bull Put Spread',
        'low_iv': 'Bull Call Spread'
    },
    'Morning_Star': {
        'high_iv': 'Iron Condor (bullish bias)',
        'low_iv': 'Long Call'
    },
    'Evening_Star': {
        'high_iv': 'Iron Condor (bearish bias)',
        'low_iv': 'Long Put'
    }
}
```

---

## 6. PATTERN PERFORMANCE TRACKING

### Built-In Learning
Every detected pattern is tracked:
- Was the prediction correct?
- What was the win rate?
- Which timeframes are most reliable?
- Which patterns work best for which sectors?

### Database Schema
```sql
CREATE TABLE pattern_detections (
    id UUID PRIMARY KEY,
    ticker TEXT NOT NULL,
    pattern TEXT NOT NULL,
    timeframes TEXT[],
    confluence_score INTEGER,
    detected_at TIMESTAMP DEFAULT NOW(),
    
    -- Outcome tracking
    suggested_strategy TEXT,
    was_traded BOOLEAN DEFAULT FALSE,
    outcome TEXT,  -- 'win', 'loss', 'timeout', 'not_traded'
    pnl DECIMAL,
    
    -- Performance metrics
    target_hit BOOLEAN,
    stop_hit BOOLEAN,
    hold_duration_minutes INTEGER
);

CREATE TABLE pattern_accuracy (
    pattern TEXT,
    timeframe TEXT,
    total_detections INTEGER,
    wins INTEGER,
    losses INTEGER,
    win_rate DECIMAL,
    average_pnl DECIMAL,
    PRIMARY KEY (pattern, timeframe)
);
```

### Feedback Loop
Strategy Discovery Agent reads pattern_accuracy table monthly and:
- Increases weight on high-performing patterns
- Decreases weight on poor performers
- Suggests new patterns to test
- Identifies anti-patterns to avoid

---

## 7. INTEGRATION WITH BOT

### Real-Time Flow
```
Every 30 seconds (crypto) or 60 seconds (stocks):
  1. Fetch latest candles
  2. Run all 12 pattern detection functions
  3. Check multi-timeframe confluence
  4. Calculate Trade Confidence Score
  5. If score >= threshold:
     - Map pattern to optimal strategy
     - Send to Risk Manager Agent
     - If approved: Trade Execution Agent places order
```

### Pseudocode
```python
async def pattern_detection_loop():
    while bot_active:
        for ticker in active_watchlist:
            try:
                # Fetch data
                candles = await fetch_candles(ticker)
                
                # Detect patterns
                patterns = detect_all_patterns(candles)
                
                # Multi-timeframe confluence
                confluence = await detect_confluence(ticker)
                
                # Score
                score, breakdown = calculate_pattern_score(
                    ticker, candles, get_market_data()
                )
                
                # Scale to Trade Confidence Score
                tcs = scale_to_trade_confidence(score, breakdown)
                
                # Check threshold
                if tcs >= user_settings.confidence_threshold:
                    strategy = PATTERN_STRATEGY_MAP[
                        patterns[0]
                    ][iv_environment]
                    
                    await emit_signal({
                        'ticker': ticker,
                        'patterns': patterns,
                        'confluence': confluence,
                        'score': tcs,
                        'strategy': strategy,
                        'breakdown': breakdown
                    })
            except Exception as e:
                log_error(e)
                continue
        
        await asyncio.sleep(30)
```

---

## 8. TESTING & VALIDATION

### Unit Tests
Every pattern function has tests with known examples:
- Real hammer candles → should detect
- Non-hammers → should not detect
- Edge cases (small bodies, zero range)
- Numerical precision tests

### Backtest Framework
Run patterns against 1 year of historical data:
- Calculate win rate per pattern
- Identify best timeframes per pattern
- Test confluence theory empirically
- Validate Trade Confidence Score correlation with outcomes

---

## 9. EXPANSION ROADMAP

### Phase 1 (Launch)
- 12 patterns implemented
- 4 timeframes
- Multi-timeframe confluence
- Trade Confidence Score

### Phase 2 (3 months)
- Add 5 more patterns based on Strategy Discovery findings
- Sector-specific pattern variations
- Pattern combinations (e.g., Hammer + RSI divergence)

### Phase 3 (6 months)
- Machine learning enhancement
- Custom pattern definition by user
- Pattern marketplace (community shared)

---

## 10. CREDIT WHERE DUE

**The founder built this engine first.** Without their ChatGPT/Codex work, Trezo's pattern detection would have taken weeks to architect. They identified the right approach:
- Mathematical pattern definition
- Multi-factor scoring
- Threshold-based alerts
- Modular design

Trezo expands this with:
- More patterns
- Multi-timeframe confluence
- Performance tracking
- Strategy mapping
- Database persistence
- Agent integration

**The seed was theirs. Trezo is the forest.**

---

*Pattern detection is the eyes of Trezo. The bot is the body. The agents are the brain.*
