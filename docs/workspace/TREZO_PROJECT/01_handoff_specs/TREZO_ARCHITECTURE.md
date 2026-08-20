# TREZO — System Architecture

## Overview
Trezo is a multi-layer automated wealth-building platform. The architecture is designed for security, scalability, and long-term maintainability with Claude Code as the permanent co-pilot.

---

## 1. HIGH-LEVEL ARCHITECTURE

```
┌────────────────────────────────────────────────────────────┐
│                     USER'S BROWSER                          │
│  ┌────────────────────────────────────────────────────┐    │
│  │  Trezo Web App (React)                             │    │
│  │  - Dashboard                                        │    │
│  │  - Trade History                                    │    │
│  │  - Settings (Sliders, Schedule, Sectors)           │    │
│  │  - KINDRIP Family Accounts                         │    │
│  └────────────────────────────────────────────────────┘    │
└──────────────────────────┬─────────────────────────────────┘
                           │ HTTPS + JWT Auth
┌──────────────────────────▼─────────────────────────────────┐
│              VERCEL (Frontend Hosting)                       │
│  - React build served globally                              │
│  - Free tier sufficient to start                            │
└──────────────────────────┬─────────────────────────────────┘
                           │ API calls
┌──────────────────────────▼─────────────────────────────────┐
│              RAILWAY (Backend Server)                        │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  FastAPI Server                                      │   │
│  │  - REST endpoints for frontend                       │   │
│  │  - WebSocket for real-time updates                   │   │
│  │  - JWT authentication                                │   │
│  └─────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Bot Engine (Python 24/7)                            │   │
│  │  - Crypto bot loop                                   │   │
│  │  - Stock bot loop (7-11AM)                          │   │
│  │  - Options scanner                                   │   │
│  │  - After-hours scanner                               │   │
│  └─────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Agent System                                        │   │
│  │  - Market Sentiment Agent                            │   │
│  │  - Risk Manager Agent                                │   │
│  │  - Tax Optimizer Agent                               │   │
│  │  - Trade Execution Agent                             │   │
│  │  - Pattern Detection Agent                           │   │
│  │  - User Support Agent                                │   │
│  │  - Research Agent                                    │   │
│  │  - Strategy Discovery Agent (Phase 3)                │   │
│  └─────────────────────────────────────────────────────┘   │
└──────────┬─────────────────────────────────────┬───────────┘
           │                                     │
           ▼                                     ▼
┌─────────────────────┐              ┌─────────────────────┐
│  SUPABASE           │              │  UPSTASH REDIS      │
│  (PostgreSQL)       │              │  (Cache Layer)      │
│  - Users            │              │  - Live prices      │
│  - Trade history    │              │  - Indicators       │
│  - Settings         │              │  - Market data      │
│  - Encrypted keys   │              │  - Session data     │
│  - KINDRIP links    │              │                     │
└─────────────────────┘              └─────────────────────┘
           │                                     │
           └──────────────┬──────────────────────┘
                          │
        ┌─────────────────┴─────────────────┐
        │                                   │
        ▼                                   ▼
┌──────────────────┐              ┌──────────────────┐
│  EXTERNAL APIs   │              │  USER BROKERAGE  │
│  - CoinGecko     │              │  - Coinbase API  │
│  - Finnhub       │              │  - Webull API    │
│  - Anthropic     │              │  (user's keys)   │
└──────────────────┘              └──────────────────┘
```

---

## 2. TECHNOLOGY STACK

### Frontend
- **Framework:** React 18+
- **Build Tool:** Vite
- **Styling:** Tailwind CSS + custom Trezo theme
- **State Management:** Zustand (lightweight)
- **Charts:** Recharts
- **WebSocket:** Native WebSocket API
- **Hosting:** Vercel

### Backend
- **Framework:** Python FastAPI
- **Async:** asyncio for concurrent bot operations
- **WebSocket:** FastAPI WebSocket support
- **Background Jobs:** APScheduler for scheduled tasks
- **Authentication:** JWT tokens
- **Hosting:** Railway

### Database
- **Primary:** PostgreSQL via Supabase
- **Cache:** Redis via Upstash
- **Encryption:** Fernet for API key storage

### External Services
- **Crypto Data:** CoinGecko (free tier, no key)
- **Stock Data:** Finnhub (free tier, 60 calls/min)
- **AI Agents:** Anthropic Claude API
- **User Brokerages:** Coinbase API, Webull API (user provides keys)

---

## 3. DIRECTORY STRUCTURE

```
trezo/
├── frontend/                    # React app
│   ├── src/
│   │   ├── components/
│   │   │   ├── Dashboard/
│   │   │   ├── TradeHistory/
│   │   │   ├── Settings/
│   │   │   ├── KINDRIP/
│   │   │   └── shared/
│   │   ├── pages/
│   │   │   ├── Landing.jsx
│   │   │   ├── Dashboard.jsx
│   │   │   ├── Settings.jsx
│   │   │   └── KINDRIP.jsx
│   │   ├── hooks/
│   │   ├── stores/
│   │   ├── utils/
│   │   └── App.jsx
│   ├── public/
│   └── package.json
│
├── backend/                     # Python FastAPI
│   ├── app/
│   │   ├── main.py             # FastAPI entry
│   │   ├── api/
│   │   │   ├── auth.py
│   │   │   ├── trades.py
│   │   │   ├── settings.py
│   │   │   ├── kindrip.py
│   │   │   └── websocket.py
│   │   ├── bot/
│   │   │   ├── crypto_bot.py
│   │   │   ├── stock_bot.py
│   │   │   ├── options_engine.py
│   │   │   └── scanner.py
│   │   ├── agents/
│   │   │   ├── base.py
│   │   │   ├── market_sentiment.py
│   │   │   ├── risk_manager.py
│   │   │   ├── tax_optimizer.py
│   │   │   ├── trade_execution.py
│   │   │   ├── pattern_detection.py
│   │   │   ├── user_support.py
│   │   │   ├── research.py
│   │   │   └── strategy_discovery.py
│   │   ├── strategies/
│   │   │   ├── stms.py         # Small Trades Momentum
│   │   │   ├── wheel.py        # Dividend Wheel
│   │   │   ├── crypto_modes.py # SCALP/SWING/DCA
│   │   │   └── options.py      # 14 options strategies
│   │   ├── indicators/
│   │   │   ├── rsi.py
│   │   │   ├── macd.py
│   │   │   ├── bollinger.py
│   │   │   ├── vwap.py
│   │   │   └── patterns.py     # Candlestick patterns
│   │   ├── data/
│   │   │   ├── coingecko.py
│   │   │   ├── finnhub.py
│   │   │   ├── coinbase.py
│   │   │   └── webull.py
│   │   ├── db/
│   │   │   ├── models.py
│   │   │   ├── crud.py
│   │   │   └── encryption.py
│   │   └── core/
│   │       ├── config.py
│   │       ├── security.py
│   │       └── scoring.py      # Trade Confidence Score
│   ├── tests/
│   ├── requirements.txt
│   └── Dockerfile
│
├── docs/                        # All TREZO_*.md files
│   ├── TREZO_MASTER_RESTORE.md
│   ├── TREZO_ARCHITECTURE.md   (this file)
│   ├── TREZO_AGENT_SPEC.md
│   ├── TREZO_API_INTEGRATION.md
│   ├── TREZO_STRATEGY_RULES.md
│   ├── TREZO_WOVEN_BASKET.md
│   ├── TREZO_PATTERN_ENGINE.md
│   ├── TREZO_DAILY_PROFIT_LOCK.md
│   ├── TREZO_FOUNDER_WATCHLIST.md
│   ├── TREZO_ETHICAL_FILTERS.md
│   ├── TREZO_PHASE_PLAN.md
│   └── TREZO_README.md
│
├── .env.example                 # Environment variables template
├── .gitignore
└── README.md
```

---

## 4. DATA FLOW

### Real-Time Price Flow (Crypto)
```
CoinGecko API
  ↓ (every 30s)
Backend fetches prices
  ↓
Redis cache updated
  ↓
WebSocket broadcasts to all connected clients
  ↓
Frontend dashboard updates live
  ↓
Indicators recalculated
  ↓
Trade signals evaluated
  ↓
Bot executes if score >= threshold
```

### Trade Execution Flow
```
Bot identifies setup (score 750+)
  ↓
Risk Manager Agent validates position size
  ↓
Trade Execution Agent prepares order
  ↓
User notified (if score < auto-threshold)
  ↓
Order sent to user's brokerage (Coinbase/Webull)
  ↓
Confirmation received
  ↓
Trade logged to PostgreSQL
  ↓
Tax Optimizer Agent updates ledger
  ↓
Frontend updates trade history
```

---

## 5. SECURITY ARCHITECTURE

### Authentication
- JWT tokens with 1-hour expiry
- Refresh tokens stored in HttpOnly cookies
- Multi-factor authentication optional (TOTP)
- Session invalidation on suspicious activity

### API Key Storage
- User's broker API keys encrypted with Fernet
- Keys stored encrypted in PostgreSQL
- Decryption only in-memory during bot execution
- Keys never logged, never displayed in plaintext after entry

### Network Security
- HTTPS only (no HTTP)
- CORS restricted to known frontends
- Rate limiting on all endpoints
- DDoS protection via Vercel/Railway

### Data Privacy
- User data never sold or shared
- No training on user trade data
- User can export and delete all data at any time
- Encrypted at rest and in transit

---

## 6. SCALING STRATEGY

### Launch (Months 0-3)
- Single Railway instance
- Free tier services
- Cost: $15-50/month
- Capacity: 1-10 users

### Growth (Months 3-12)
- Upgraded Railway plan
- Paid Supabase tier
- Cost: $100-300/month
- Capacity: 50-500 users

### Scale (Year 2+)
- Migrate to AWS
- Kubernetes for bot processes
- Read replicas for database
- Cost: $500-2000/month
- Capacity: 1000+ users

---

## 7. RELIABILITY & MONITORING

### Health Checks
- Backend health endpoint
- Bot heartbeat every 30 seconds
- API connectivity checks
- Database connection pooling

### Logging
- Structured JSON logs
- Trade events to permanent storage
- Error tracking via Sentry
- Performance monitoring

### Backup
- Daily PostgreSQL backups
- Trade history immutable (audit trail)
- Configuration backups versioned

---

## 8. DEPLOYMENT PIPELINE

### Development
1. Local development on user's Windows machine
2. Git commits to GitHub
3. Pull requests reviewed (by Claude Code)
4. Tests run automatically

### Staging
1. Auto-deploy to staging on merge to develop
2. Manual testing
3. Performance validation

### Production
1. Manual promotion from staging
2. Blue-green deployment
3. Automated rollback if errors detected

---

## 9. MAINTENANCE PLAN

### Routine (Monthly)
- Dependency updates
- Security patches
- API key rotations

### Quarterly
- Performance review
- Cost optimization
- Feature additions per Phase plan

### Annual
- Tax bracket updates
- Strategy review
- Major version upgrades

**All maintenance done through Claude Code conversations — user never needs to write code directly.**

---

## 10. DISASTER RECOVERY

If everything fails:
1. PostgreSQL backup restores all data
2. Encrypted API keys remain in backup
3. Bot resumes from last known state
4. User notified of any data loss
5. Trezo always recoverable from this architecture document

---

*Architecture designed for: 1 user → 10,000 users without ground-up rewrite.*
