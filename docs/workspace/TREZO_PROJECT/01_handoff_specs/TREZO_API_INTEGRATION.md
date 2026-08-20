# TREZO — API Integration Specification

## Overview
Trezo integrates with 4 external API services. This document specifies exact endpoints, rate limits, fallback strategies, and authentication patterns.

---

## 1. COINGECKO API (Crypto Data)

### Purpose
Real-time crypto prices and OHLCV data for XRP, ETH, SOL.

### Authentication
**None required** for free tier.

### Base URL
```
https://api.coingecko.com/api/v3
```

### Rate Limit
- Free tier: 10-30 calls/minute
- Trezo strategy: 1 call every 30 seconds (well within limit)

### Endpoints Used

**1. Simple Price (current prices + 24hr change)**
```
GET /simple/price
  ?ids=ripple,ethereum,solana
  &vs_currencies=usd
  &include_24hr_change=true
  &include_last_updated_at=true
```

Response:
```json
{
  "ripple": {"usd": 2.45, "usd_24h_change": 1.8, "last_updated_at": 1747084800},
  "ethereum": {"usd": 3420.50, "usd_24h_change": 2.1, "last_updated_at": 1747084800},
  "solana": {"usd": 187.30, "usd_24h_change": -0.5, "last_updated_at": 1747084800}
}
```

**2. Market Chart (OHLCV for indicators)**
```
GET /coins/{id}/market_chart
  ?vs_currency=usd
  &days=2
  &interval=hourly
```

Returns prices, market_caps, and total_volumes arrays.

### Fallback Strategy
If CoinGecko fails:
1. Wait 30 seconds and retry
2. After 3 failures, switch to Coinbase public price endpoint
3. Log error to user dashboard
4. Continue operating in degraded mode

### Caching
- Prices cached in Redis for 30 seconds
- OHLCV cached for 5 minutes
- All clients share same cache

---

## 2. FINNHUB API (Stock Data)

### Purpose
Real-time stock quotes, candles, news, earnings calendar.

### Authentication
API Key in URL parameter: `?token=YOUR_KEY`

**IMPORTANT:** The original key shared in chat MUST be regenerated at finnhub.io/dashboard before production use.

### Base URL
```
https://finnhub.io/api/v1
```

### Rate Limit
- Free tier: 60 calls/minute
- Trezo strategy: Distributed across watchlist, ~30 calls/minute typical

### Endpoints Used

**1. Stock Quote**
```
GET /quote
  ?symbol={SYMBOL}
  &token={KEY}
```

Response:
```json
{
  "c": 187.45,    // current
  "h": 189.20,    // high
  "l": 185.30,    // low
  "o": 186.50,    // open
  "pc": 186.00,   // previous close
  "d": 1.45,      // change
  "dp": 0.78,     // change percent
  "t": 1747084800 // timestamp
}
```

**2. Stock Candles**
```
GET /stock/candle
  ?symbol={SYMBOL}
  &resolution={1,5,15,30,60,D,W}
  &from={UNIX_TIME}
  &to={UNIX_TIME}
  &token={KEY}
```

**3. Company News**
```
GET /company-news
  ?symbol={SYMBOL}
  &from={YYYY-MM-DD}
  &to={YYYY-MM-DD}
  &token={KEY}
```

**4. Earnings Calendar**
```
GET /calendar/earnings
  ?from={YYYY-MM-DD}
  &to={YYYY-MM-DD}
  &token={KEY}
```

**5. Market News**
```
GET /news
  ?category=general
  &token={KEY}
```

### Fallback Strategy
If Finnhub fails:
1. Retry once after 5 seconds
2. Use Yahoo Finance via web scraping as backup
3. Cache last known prices for graceful degradation
4. Notify user of degraded mode

### Caching
- Quotes cached for 60 seconds
- Candles cached for 5 minutes
- News cached for 15 minutes

---

## 3. ANTHROPIC API (Agent Intelligence)

### Purpose
Power all 8 agents with Claude language model.

### Authentication
```
x-api-key: YOUR_API_KEY
anthropic-version: 2023-06-01
```

### Base URL
```
https://api.anthropic.com/v1
```

### Endpoints Used

**1. Messages (primary endpoint)**
```
POST /messages
Content-Type: application/json

{
  "model": "claude-sonnet-4-20250514",
  "max_tokens": 1024,
  "messages": [
    {"role": "user", "content": "Analyze this trade setup..."}
  ]
}
```

### Models Used
- **claude-sonnet-4-20250514** — Default for all agents
- **claude-opus-4** — Strategy Discovery Agent only (complex reasoning)

### Cost Estimation
- Sonnet 4: $3/M input tokens, $15/M output tokens
- Typical agent call: 1000 input + 200 output = $0.006
- Daily calls: 1000-5000 across all agents
- Estimated cost: $10-30/month at low volume

### Rate Limit Handling
- Built-in retry logic with exponential backoff
- Queue requests when approaching limits
- Priority queue for time-sensitive decisions

### Web Search Tool (when needed)
```json
{
  "tools": [
    {"type": "web_search_20250305", "name": "web_search"}
  ]
}
```

Used by:
- Market Sentiment Agent (breaking news)
- Research Agent (deep dives)
- User Support Agent (answering questions)

---

## 4. COINBASE API (User's Crypto Trading)

### Purpose
Execute trades on user's behalf via their Coinbase account.

### Authentication
**User provides their own API keys.**
- CDP API Key Name
- Private Key (RSA)
- Stored encrypted in Trezo database
- Never displayed in plaintext after entry

### Base URL
```
https://api.coinbase.com/api/v3/brokerage
```

### Endpoints Used

**1. List Accounts**
```
GET /accounts
```
Returns user's account balances.

**2. Get Best Bid/Ask**
```
GET /best_bid_ask
  ?product_ids=XRP-USD,ETH-USD,SOL-USD
```

**3. Create Order**
```
POST /orders
{
  "client_order_id": "uuid",
  "product_id": "XRP-USD",
  "side": "BUY",
  "order_configuration": {
    "limit_limit_gtc": {
      "base_size": "100",
      "limit_price": "2.45"
    }
  }
}
```

**4. List Orders**
```
GET /orders/historical/batch
  ?product_id=XRP-USD
```

**5. Cancel Order**
```
POST /orders/batch_cancel
{
  "order_ids": ["uuid"]
}
```

### Security
- API keys with TRADE permission only (no withdraw)
- Keys can be revoked instantly by user
- All trades logged for audit trail

---

## 5. WEBULL API (User's Stock Trading)

### Status
**Note:** Webull's official API access is limited. Initial Trezo implementation focuses on:
1. Read-only account info via Webull OpenAPI
2. User executes stock trades manually via Webull app
3. Trezo provides signals + suggested orders

### Future
When Webull OpenAPI provides full trading access, full automation will be implemented.

### Alternative: Alpaca
For users who want full stock trading automation, Trezo will support Alpaca as alternative broker:
- Free API access
- Full trade execution
- Paper trading mode built-in

---

## 6. SUPABASE (Database)

### Connection
```python
from supabase import create_client

supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_KEY")
supabase = create_client(supabase_url, supabase_key)
```

### Tables Schema

**users**
```sql
CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT NOW(),
  filing_status TEXT DEFAULT 'single',
  income DECIMAL,
  marginal_rate DECIMAL,
  ltcg_rate DECIMAL
);
```

**broker_credentials** (encrypted)
```sql
CREATE TABLE broker_credentials (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id),
  broker TEXT NOT NULL,
  encrypted_key TEXT NOT NULL,
  encrypted_secret TEXT,
  created_at TIMESTAMP DEFAULT NOW()
);
```

**trades**
```sql
CREATE TABLE trades (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id),
  ticker TEXT NOT NULL,
  type TEXT NOT NULL,  -- 'stock', 'options', 'crypto'
  side TEXT NOT NULL,  -- 'buy', 'sell'
  quantity DECIMAL NOT NULL,
  price DECIMAL NOT NULL,
  pnl DECIMAL,
  tax_owed DECIMAL,
  net_pnl DECIMAL,
  pattern TEXT,
  score INTEGER,
  catalyst TEXT,
  entered_at TIMESTAMP DEFAULT NOW(),
  exited_at TIMESTAMP
);
```

**watchlists**
```sql
CREATE TABLE watchlists (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id),
  name TEXT NOT NULL,
  tickers TEXT[],
  created_at TIMESTAMP DEFAULT NOW()
);
```

**settings**
```sql
CREATE TABLE settings (
  user_id UUID PRIMARY KEY REFERENCES users(id),
  aggression INTEGER DEFAULT 5,
  daily_profit_target DECIMAL DEFAULT 50,
  daily_loss_limit DECIMAL DEFAULT 100,
  active_layers JSONB,
  ethical_filters JSONB,
  schedule JSONB
);
```

**kindrip_links**
```sql
CREATE TABLE kindrip_links (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  parent_id UUID REFERENCES users(id),
  child_id UUID REFERENCES users(id),
  allocation_percent DECIMAL,
  allocation_type TEXT,
  age_threshold TEXT
);
```

**daily_lock_vault**
```sql
CREATE TABLE daily_lock_vault (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id),
  date DATE NOT NULL,
  amount_locked DECIMAL NOT NULL,
  source TEXT,
  unlocked_at TIMESTAMP
);
```

---

## 7. UPSTASH REDIS (Cache)

### Connection
```python
import redis
r = redis.from_url(os.environ.get("UPSTASH_REDIS_URL"))
```

### Cache Keys

**Price data:**
- `price:crypto:{symbol}` (TTL: 30s)
- `price:stock:{symbol}` (TTL: 60s)

**Indicators:**
- `indicators:{symbol}:{timeframe}` (TTL: 5min)

**Patterns:**
- `patterns:{symbol}:{timeframe}` (TTL: 5min)

**Market state:**
- `market:cycle` (TTL: 5min)
- `market:vix` (TTL: 1min)

**User session:**
- `session:{user_id}` (TTL: 1hr)
- `bot_state:{user_id}` (no TTL, persistent state)

### Pub/Sub Channels
- `trezo:signals` — Pattern Detection broadcasts
- `trezo:execution` — Trade Execution events
- `trezo:risk` — Risk Manager alerts
- `trezo:tax` — Tax Optimizer events
- `trezo:research` — Research Agent updates
- `trezo:user:{user_id}` — User-specific events

---

## 8. ENVIRONMENT VARIABLES

```bash
# Frontend (.env.local)
VITE_API_URL=https://api.trezo.app
VITE_WEBSOCKET_URL=wss://api.trezo.app/ws

# Backend (.env)
# Database
SUPABASE_URL=https://xxxxx.supabase.co
SUPABASE_KEY=eyJxxxxx
UPSTASH_REDIS_URL=redis://xxxxx

# External APIs
FINNHUB_API_KEY=xxxxx  # REGENERATED key
ANTHROPIC_API_KEY=sk-ant-xxxxx
COINGECKO_API_URL=https://api.coingecko.com/api/v3

# Security
JWT_SECRET=xxxxx
ENCRYPTION_KEY=xxxxx
JWT_EXPIRY_HOURS=1

# Bot Configuration
BOT_LOOP_INTERVAL_SECONDS=20
CRYPTO_FETCH_INTERVAL_SECONDS=30
STOCK_FETCH_INTERVAL_SECONDS=60
MARKET_FETCH_INTERVAL_SECONDS=300

# Trading Configuration
MAX_DAILY_LOSS_PERCENT=10
MAX_POSITION_PERCENT=5
MIN_TRADE_CONFIDENCE_SCORE=750
```

---

## 9. ERROR HANDLING PATTERNS

### Retry with Exponential Backoff
```python
async def fetch_with_retry(url, max_retries=3):
    for attempt in range(max_retries):
        try:
            response = await fetch(url)
            if response.ok:
                return response.json()
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(2 ** attempt)
```

### Circuit Breaker
```python
class CircuitBreaker:
    def __init__(self, failure_threshold=5, recovery_timeout=60):
        self.failures = 0
        self.last_failure = None
        self.threshold = failure_threshold
        self.timeout = recovery_timeout
    
    def call(self, fn, *args):
        if self.is_open():
            raise Exception("Circuit breaker open")
        try:
            result = fn(*args)
            self.reset()
            return result
        except Exception as e:
            self.record_failure()
            raise
```

### Graceful Degradation
- If CoinGecko down → use cached prices for 5 minutes
- If Finnhub down → pause stock trading, continue crypto
- If Anthropic down → disable agent features, basic bot continues
- If broker API down → halt new trades, manage existing positions

---

## 10. WEBSOCKET PROTOCOL

### Client → Server
```json
{
  "type": "subscribe",
  "channels": ["prices", "trades", "alerts"]
}
```

### Server → Client

**Price Update:**
```json
{
  "type": "price",
  "ticker": "XRP",
  "price": 2.45,
  "change": 1.8,
  "timestamp": "2026-05-13T14:30:00Z"
}
```

**Trade Executed:**
```json
{
  "type": "trade",
  "action": "executed",
  "ticker": "AMD",
  "side": "buy",
  "quantity": 1,
  "price": 168.50,
  "pattern": "Hammer",
  "score": 87
}
```

**Agent Alert:**
```json
{
  "type": "alert",
  "agent": "risk_manager",
  "severity": "warning",
  "message": "Approaching 80% of daily loss limit"
}
```

---

## 11. TESTING STRATEGY

### Unit Tests
- Each indicator function tested with known inputs
- Each agent's logic tested independently
- Mock external APIs for repeatability

### Integration Tests
- End-to-end trade flow
- WebSocket message handling
- Database transactions

### Paper Trading
- Phase 1 mandatory paper trading mode
- All logic runs but no real orders placed
- Allows validation before risking capital

---

*All APIs documented. Ready for Claude Code to build against.*
