# TREZO — PHASE PLAN

## Purpose
Step-by-step build order for Claude Code. Each phase has clear deliverables, checkboxes, and exit criteria. Don't skip phases. Don't combine phases.

---

## PHASE 0: FOUNDATION (Week 1)

### Goal
Get the development environment running and project skeleton in place.

### Tasks

#### Environment Setup
- [ ] Verify Node.js 20+ installed (`node --version`)
- [ ] Verify Python 3.11+ installed (`python --version`)
- [ ] Install pnpm globally (`npm install -g pnpm`)
- [ ] Install VS Code with extensions: ESLint, Prettier, Python, Tailwind
- [ ] Install Claude Code CLI
- [ ] Install Postman (for API testing)
- [ ] Install Git and configure SSH keys

#### API Keys Acquisition
- [ ] **Regenerate Finnhub API key** at finnhub.io/dashboard (the previously shared key in chat must be invalidated)
- [ ] Create Anthropic API key at console.anthropic.com
- [ ] Note CoinGecko works without API key (CORS-safe public endpoints)
- [ ] Coinbase API: defer until Phase 4 (read-only access initially)

#### Account Setup
- [ ] Create Vercel account (vercel.com) — free tier
- [ ] Create Railway account (railway.app) — $5/month starter
- [ ] Create Supabase account (supabase.com) — free tier
- [ ] Create Upstash Redis account (upstash.com) — free tier
- [ ] Create GitHub repo: `trezo-platform`
- [ ] Configure secrets management (.env file, never commit)

#### Project Skeleton
- [ ] Initialize monorepo structure (see TREZO_ARCHITECTURE.md)
- [ ] Set up Next.js 14 app in `/web`
- [ ] Set up Express API server in `/api`
- [ ] Set up Python agents in `/agents`
- [ ] Configure Tailwind CSS
- [ ] Configure shadcn/ui components
- [ ] Set up Supabase database schema
- [ ] Run initial database migrations
- [ ] Set up CI/CD pipeline (GitHub Actions → Vercel + Railway)

### Exit Criteria
- ✅ Hello World page renders at localhost:3000
- ✅ API health check responds at localhost:8000/health
- ✅ Database connection verified
- ✅ Deployed dev environment URL works

---

## PHASE 1: LANDING + AUTH (Week 2)

### Goal
Public landing page + user authentication. Foundation users can sign in.

### Tasks

#### Landing Page
- [ ] Build clean "Trezo" branding header
- [ ] Hero section with tagline: "Layer by Layer. Trade by Trade."
- [ ] Seven Layers visual (without full functionality)
- [ ] Sign up / Sign in CTAs
- [ ] Woven Basket philosophy quote at bottom of landing page
- [ ] Footer with privacy + terms placeholders
- [ ] Mobile responsive

#### Authentication
- [ ] Supabase Auth integration
- [ ] Sign up flow (email + password)
- [ ] Sign in flow
- [ ] Password reset flow
- [ ] Email verification
- [ ] Session management
- [ ] Protected routes middleware

#### User Profile
- [ ] Profile setup wizard (first login)
- [ ] Capital input (stock account size, crypto holdings)
- [ ] Risk tolerance selector
- [ ] Daily profit target input
- [ ] Tax filing status
- [ ] Save to `users` table

### Exit Criteria
- ✅ Anonymous user sees landing page
- ✅ User can sign up
- ✅ User can sign in / sign out
- ✅ Profile data persists

---

## PHASE 2: DASHBOARD + DATA INTEGRATION (Week 3)

### Goal
Authenticated dashboard that displays real market data. No trading yet.

### Tasks

#### Dashboard Shell
- [ ] Build main dashboard layout
- [ ] Navigation sidebar with seven layers
- [ ] Top bar with account summary
- [ ] Settings menu
- [ ] Mobile hamburger menu

#### CoinGecko Integration
- [ ] Service wrapper for CoinGecko API
- [ ] Cache layer (Redis, 30s TTL)
- [ ] Live prices for XRP, ETH, SOL
- [ ] Display crypto portfolio value
- [ ] 24h change indicators

#### Finnhub Integration
- [ ] Service wrapper for Finnhub API
- [ ] Rate limit management (60 calls/minute on free tier)
- [ ] Live quotes for watchlist tickers
- [ ] Company profiles
- [ ] News feed (per ticker)

#### YieldMax Tracker
- [ ] Display founder's positions (AIYY, AMZY, GOOY, NVDY, TSLY)
- [ ] Show share count, current value, cumulative distributions
- [ ] NAV health indicator (price trend over 30 days)

### Exit Criteria
- ✅ Live crypto prices on dashboard
- ✅ Live stock quotes update every 60 seconds
- ✅ YieldMax positions display correctly
- ✅ Mobile view works

---

## PHASE 3: WATCHLIST + ETHICAL FILTERS (Week 4)

### Goal
User can manage watchlists with ethical filtering applied.

### Tasks

#### Watchlist Management
- [ ] Seed default watchlist from TREZO_FOUNDER_WATCHLIST.md
- [ ] Add ticker UI (with autocomplete)
- [ ] Remove ticker (with confirmation)
- [ ] Create custom lists (named groups)
- [ ] Star favorites
- [ ] Drag-to-reorder
- [ ] Per-ticker notes field
- [ ] CSV import

#### Ethical Filter System
- [ ] Build exclusion database (see TREZO_ETHICAL_FILTERS.md)
- [ ] Seed with current SAM.gov data
- [ ] Build daily sync job
- [ ] Filter check function
- [ ] Block flow with reason display
- [ ] Override flow (with logging)
- [ ] User settings UI for opt-in categories

### Exit Criteria
- ✅ User can add/remove tickers
- ✅ Excluded tickers blocked with clear reasons
- ✅ User can toggle ethical filter categories
- ✅ Default watchlist loads on first sign-in

---

## PHASE 4: PATTERN DETECTION ENGINE (Week 5-6)

### Goal
Implement the Pattern Detection Agent based on founder's Codex code.

### Tasks

#### Foundation (from Codex code)
- [ ] Port `isHammer()` function to Python
- [ ] Port 6-factor scoring system
- [ ] Add unit tests for each factor

#### Expansion to 12 Patterns
- [ ] Hammer / Inverted Hammer
- [ ] Doji (standard, dragonfly, gravestone)
- [ ] Engulfing (bullish + bearish)
- [ ] Morning Star / Evening Star
- [ ] Three White Soldiers / Three Black Crows
- [ ] Shooting Star
- [ ] Hanging Man
- [ ] Piercing Pattern
- [ ] Dark Cloud Cover
- [ ] Harami
- [ ] Tweezer Tops/Bottoms
- [ ] Spinning Top

#### Multi-Timeframe Confluence
- [ ] 5-minute pattern scan
- [ ] 15-minute pattern scan
- [ ] 1-hour pattern scan
- [ ] Daily pattern scan
- [ ] Confluence scoring (patterns aligning across timeframes)

#### Options Pattern Scoring
- [ ] Score patterns specifically for options trading
- [ ] Weight by IV environment
- [ ] Weight by days-to-expiration optimal range
- [ ] Output Trade Confidence Score (TCS) 0-10

### Exit Criteria
- ✅ Pattern detection runs every 60s on watchlist
- ✅ TCS displayed for each ticker
- ✅ Backtesting shows >55% accuracy on hammer + engulfing combo
- ✅ Pattern alerts appear in dashboard

---

## PHASE 5: AGENT ARCHITECTURE (Week 7-8)

### Goal
Stand up all 8 agents in observe-only mode.

### Tasks

#### Agent Infrastructure
- [ ] Build agent base class
- [ ] Build inter-agent communication bus
- [ ] Build agent logging system
- [ ] Build agent permissions matrix

#### Individual Agents (see TREZO_AGENT_SPEC.md)
- [ ] Market Sentiment Agent (Finnhub news + RSS)
- [ ] Risk Manager Agent (highest authority)
- [ ] Tax Optimizer Agent (real-time ledger)
- [ ] Trade Execution Agent (paper trading only Phase 5)
- [ ] Pattern Detection Agent (from Phase 4)
- [ ] User Support Agent (Q&A via Anthropic API)
- [ ] Research Agent (watchlists, scans)
- [ ] Strategy Discovery Agent (Phase 3 only — defer logic, build shell)

#### Agent Dashboard
- [ ] Live agent activity feed
- [ ] Per-agent log viewer
- [ ] Agent enable/disable toggles
- [ ] Agent confidence indicators

### Exit Criteria
- ✅ All 8 agents run without errors
- ✅ Agents communicate via bus
- ✅ User can see agent activity in real-time
- ✅ Risk Manager can veto simulated trades

---

## PHASE 6: PAPER TRADING (Week 9-10)

### Goal
Full strategy execution in simulated environment. No real money yet.

### Tasks

#### Paper Trading Engine
- [ ] Simulated account with starting capital
- [ ] Simulated order book
- [ ] Realistic slippage modeling
- [ ] Commission simulation
- [ ] P&L tracking
- [ ] Position management

#### Strategies (see TREZO_STRATEGY_RULES.md)
- [ ] STMS (Small Trades Momentum Strategy) — 7-11 AM
- [ ] Crypto bot (XRP/ETH/SOL)
- [ ] Dividend Wheel (covered calls + CSP)
- [ ] Options strategies (start with 3 of 14)

#### Daily Profit Lock
- [ ] User sets daily target
- [ ] Auto-transfer logic
- [ ] Vault display
- [ ] Vault withdrawal flow

### Exit Criteria
- ✅ Paper bot runs for 5 consecutive days
- ✅ Daily Profit Lock saves correctly
- ✅ All strategies execute without errors
- ✅ Performance dashboard shows realistic results

---

## PHASE 7: TAX OPTIMIZER + REPORTING (Week 11)

### Goal
Real-time tax tracking and quarterly estimate generation.

### Tasks
- [ ] Cost basis tracking per position
- [ ] Short-term vs long-term classification
- [ ] Wash sale detection
- [ ] Federal + state estimate calculations
- [ ] Quarterly estimated tax reports
- [ ] Year-end tax summary export
- [ ] Schedule D / 1099-B compatible CSV

### Exit Criteria
- ✅ Every trade contributes to tax ledger
- ✅ User can see YTD realized gains/losses
- ✅ Quarterly estimates calculated correctly
- ✅ Export matches IRS format

---

## PHASE 8: KINDRIP CHILD PORTFOLIO (Week 12)

### Goal
Multi-generational wealth feature.

### Tasks
- [ ] Child profile setup
- [ ] UTMA/UGMA account linking guidance
- [ ] Auto-invest allocation (40% SCHD / 30% VTI / 20% BND / 10% cash)
- [ ] Contribution scheduling
- [ ] Education milestone tracking
- [ ] Inheritance planning section
- [ ] Quarterly child portfolio reports

### Exit Criteria
- ✅ Parent can add child profile
- ✅ Auto-invest allocations execute
- ✅ Quarterly reports generate

---

## PHASE 9: REAL MONEY INTEGRATION (Week 13-14)

### Goal
Connect to real brokerage accounts.

### Tasks
- [ ] Webull API integration (research feasibility)
- [ ] Alternative: IBKR API integration
- [ ] Account linking flow (OAuth where possible)
- [ ] Read-only mode first (positions sync, no trades)
- [ ] Trade execution mode (with multi-factor confirmation)
- [ ] Coinbase API for crypto execution
- [ ] Audit log of all real trades

### Exit Criteria
- ✅ User can connect Webull account
- ✅ Positions sync correctly
- ✅ Test trade executes (minimum size)
- ✅ All trades logged with broker confirmation IDs

---

## PHASE 10: STRATEGY DISCOVERY AGENT — FULL ACTIVATION (Week 15)

### Goal
Activate the Phase 3 agent that analyzes user patterns.

### Tasks
- [ ] Analyze user's actual trade history
- [ ] Identify winning pattern clusters
- [ ] Suggest watchlist additions
- [ ] Identify counter-patterns (when to avoid)
- [ ] Sector rotation discovery
- [ ] Anti-pattern detection (averaging down, etc.)
- [ ] Weekly strategy report

### Exit Criteria
- ✅ Agent generates weekly insights
- ✅ Suggestions are specific and actionable
- ✅ User can accept/reject suggestions
- ✅ Bot learns from rejections

---

## PHASE 11: POLISH + LAUNCH PREP (Week 16)

### Goal
Production readiness.

### Tasks
- [ ] Full security audit
- [ ] Performance optimization
- [ ] Error monitoring (Sentry)
- [ ] Analytics (privacy-respecting — Plausible)
- [ ] Terms of Service
- [ ] Privacy Policy
- [ ] Onboarding tutorial
- [ ] Help documentation
- [ ] Marketing site
- [ ] Beta user invites

### Exit Criteria
- ✅ Zero critical bugs
- ✅ Load tested
- ✅ Legal docs reviewed
- ✅ First 10 beta users invited

---

## DEFERRED — POST-LAUNCH

These are valuable but not blocking initial launch:

- Desktop app (Electron wrapper)
- Mobile app (React Native)
- Community features
- Strategy marketplace
- Multi-account management
- Family tier (multiple users)
- Premium tier ($/month for advanced features)
- White-label B2B offering

---

## CRITICAL PATH NOTES

**These must happen in order:**
1. Foundation → Auth → Dashboard
2. Pattern Engine → Agents → Paper Trading → Real Trading

**These can happen in parallel:**
- Watchlist + Ethical Filters can build alongside Pattern Engine
- Tax Optimizer can build alongside Paper Trading
- KINDRIP can build alongside Real Money Integration

**Never skip:**
- Phase 6 (Paper Trading) before Phase 9 (Real Money)
- Phase 11 (Polish) before public launch

---

## ESTIMATED TIMELINE

- **Solo developer:** 16 weeks (~4 months)
- **2 developers:** 10 weeks (~2.5 months)
- **3+ developers:** 8 weeks (~2 months)

Founder is doing this with Claude Code as co-developer. Realistic estimate: **3-5 months to MVP launch.**

---

## COST ESTIMATES (Monthly)

| Service | Phase | Cost |
|---|---|---|
| Vercel | All | $0 (hobby) → $20 (pro at scale) |
| Railway | All | $5 → $20 |
| Supabase | All | $0 (free) → $25 (pro at scale) |
| Upstash Redis | All | $0 (free) → $10 |
| Finnhub | Phase 2+ | $0 (free) → $20-100 (paid tiers) |
| Anthropic API | Phase 5+ | ~$10-50 (varies with usage) |
| Domain | Phase 11 | $12/year |
| **TOTAL** | **Start** | **~$15/month** |
| **TOTAL** | **At scale** | **~$50-200/month** |

---

## END OF PHASE PLAN
