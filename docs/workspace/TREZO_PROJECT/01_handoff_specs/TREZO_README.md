# TREZO

> **Layer by Layer. Trade by Trade.**
> 
> Like Maternal Love — not everything will be ok, but the love tries to keep whatever it is protecting safe, layer after layer, giving its all.

---

## What is Trezo?

Trezo (from Haitian Creole *Trezò* — "Treasure") is a multi-layer automated trading platform that makes institutional-grade wealth building accessible to every family.

It's not a trading bot. It's a **woven basket** of seven protective layers that work together to build wealth slowly, safely, and ethically.

---

## The Seven Layers

| # | Layer | Purpose |
|---|---|---|
| 1 | Crypto Bot | 24/7 trading of XRP, ETH, SOL on Coinbase |
| 2 | Stock Bot (STMS) | 7-11 AM small-cap momentum scalping |
| 3 | Options Engine | Pattern-driven multi-strategy options trading |
| 4 | Dividend Wheel | Covered calls + cash-secured puts |
| 5 | YieldMax Portfolio | Weekly distribution income engine |
| 6 | Tax Optimizer | Real-time P&L + quarterly estimates |
| 7 | Extended Strategy | Swing trades, penny stocks, event-driven plays |

Each layer protects the ones beneath it. When one struggles, others carry the weight.

---

## Quickstart for Claude Code

### Step 1: Read the Master Restore
```
Open: TREZO_MASTER_RESTORE.md
```
This file contains the full project state, decisions, and resume instructions.

### Step 2: Read the Phase Plan
```
Open: TREZO_PHASE_PLAN.md
```
Start at Phase 0. Don't skip phases.

### Step 3: Read Architecture
```
Open: TREZO_ARCHITECTURE.md
```
This is the technical foundation — directory structure, data flow, security.

### Step 4: Reference As Needed
Other docs provide deep specs for specific subsystems:
- Pattern detection logic → `TREZO_PATTERN_ENGINE.md`
- Agent behavior → `TREZO_AGENT_SPEC.md`
- API endpoints → `TREZO_API_INTEGRATION.md`
- Strategy rules → `TREZO_STRATEGY_RULES.md`
- Watchlist → `TREZO_FOUNDER_WATCHLIST.md`
- Ethical filters → `TREZO_ETHICAL_FILTERS.md`
- Daily Profit Lock → `TREZO_DAILY_PROFIT_LOCK.md`
- Woven Basket + KINDRIP → `TREZO_WOVEN_BASKET.md`

---

## File Index

### Core Files (Required Reading)
| File | Purpose | Lines |
|---|---|---|
| TREZO_README.md | This file — entry point | ~300 |
| TREZO_MASTER_RESTORE.md | Project state + resume command | ~320 |
| TREZO_ARCHITECTURE.md | Tech stack + system design | ~380 |
| TREZO_PHASE_PLAN.md | Build order with checkboxes | ~350 |
| TREZO_AGENT_SPEC.md | 8 agents specified | ~530 |
| TREZO_API_INTEGRATION.md | All API endpoints + schemas | ~610 |
| TREZO_STRATEGY_RULES.md | STMS, Wheel, Options strategies | ~510 |
| TREZO_PATTERN_ENGINE.md | Pattern detection (from founder's Codex) | ~600 |
| TREZO_WOVEN_BASKET.md | Philosophy + KINDRIP child portfolio | ~410 |
| TREZO_DAILY_PROFIT_LOCK.md | User's profit-save rule implementation | ~490 |
| TREZO_FOUNDER_WATCHLIST.md | Calibrated watchlist from real trading data | ~200 |
| TREZO_ETHICAL_FILTERS.md | ESG screening with user controls | ~200 |

### Advanced Strategy Additions (v4 — Based on Study Materials)
| File | Purpose | Lines |
|---|---|---|
| TREZO_CREDIT_SPREADS.md | Defined-risk income strategy | ~400 |
| TREZO_DAY_TRADING_REFINEMENTS.md | MACD + Volume confluence rule | ~350 |
| TREZO_TAX_STRATEGIES.md | TTS, 475(f), LLC structures | ~400 |

---

## Tech Stack (Quick Reference)

**Frontend:**
- Next.js 14 (App Router)
- React 18
- TypeScript
- Tailwind CSS
- shadcn/ui

**Backend:**
- Node.js / Express (API gateway)
- Python 3.11 (agents + ML)
- PostgreSQL (Supabase)
- Redis (Upstash) for caching

**Hosting:**
- Vercel (frontend)
- Railway (backend + agents)
- Supabase (database + auth)

**External APIs:**
- Finnhub (stocks data + news) — NEEDS NEW API KEY
- CoinGecko (crypto prices, no key needed)
- Anthropic Claude API (agent intelligence)
- Coinbase API (crypto trading — Phase 4+)
- Webull API or IBKR API (stock trading — Phase 9+)

---

## Critical Decisions (Locked)

- ✅ **Phase 1+2 built together** — agents present from day one
- ✅ **Web app first** → Desktop (Electron) → Mobile (React Native) post-launch
- ✅ **Cloud hosting from day one** — no 24/7 home computer needed
- ✅ **User-owned accounts** — 3Commas/Cryptohopper legal model (we don't custody funds)
- ✅ **Conservative KINDRIP allocation** — 40% SCHD / 30% VTI / 20% BND / 10% cash for child portfolios
- ✅ **Strategy Discovery Agent in Phase 3** — bot identifies missing strategies
- ✅ **Ethical filters default-on** — human rights violators excluded
- ✅ **Daily Profit Lock** — user's "save the minimum daily target" rule

---

## Founder Profile (Summary)

- **Capital:** $500-2,000 stock account, $4,636 crypto, $1,000 options starting
- **Brokers:** Webull (stocks), Coinbase (crypto)
- **Tax:** Single filer, ~$30K income, 12% marginal ST rate, 0% LTCG
- **OS:** Windows, no 24/7 home computer
- **Trading history:** 60+ positions analyzed, net positive ~$1,300, key strengths in patient swing trading on mid-caps (CZR, AMD, INTC, WMT, AMSC) and YieldMax dividend stack

**Demonstrated Edge:**
- Semiconductors
- Gaming (CZR specifically)
- Retail (WMT)
- YieldMax dividend stack

**Identified Weaknesses (Trezo solves these):**
- Averaging down on losers (SOUN -$1,079)
- Holding past optimal exit (AAPL -$377)
- Spreading too thin across 60+ names
- No systematic stop enforcement

---

## Critical Actions for User (Pre-Build)

Before Claude Code can start building, these must happen:

- [ ] **Regenerate Finnhub API key** — old one was shared in chat and must be invalidated. Visit finnhub.io/dashboard
- [ ] **Create Anthropic API key** — console.anthropic.com
- [ ] **Install Node.js 20+** — nodejs.org
- [ ] **Install Python 3.11+** — python.org
- [ ] **Install VS Code** — code.visualstudio.com
- [ ] **Install Claude Code CLI** — see Anthropic docs
- [ ] **Install Git** — git-scm.com
- [ ] **Install Postman** — postman.com
- [ ] **Create accounts:** Vercel, Railway, Supabase, Upstash Redis (all free tiers to start)

**Estimated monthly cost to run dev environment:** $15-50 (Railway $5-20, others free tier)

---

## Build Philosophy

**Don't rush.** This is a wealth-building platform. Bugs cost real money.

**Test everything.** Every strategy must paper-trade before real money.

**Respect the user.** They control everything. Bot suggests, user approves (Phase 2). Bot executes only in Phase 3+.

**Transparency over magic.** Every decision the bot makes has a reason the user can see.

**Patience over speed.** This isn't a get-rich-quick tool. It's a get-wealthy-over-years tool.

---

## Support & Maintenance

**Bug reports:** Document in GitHub Issues
**Strategy refinements:** Update relevant `.md` spec file first, then code
**Security incidents:** Stop all trading, audit logs, restore from backup
**API changes:** Monitor Finnhub/Coinbase changelogs weekly

---

## Resume Command for Future Sessions

If continuing this project with Nova (Claude) in a future session:

> "Nova, I'm resuming the Trezo project. Read TREZO_MASTER_RESTORE.md and we'll continue building."

---

## Brand & Voice Guidelines

**Brand name:** Trezo (always capitalized as "Trezo" in body text, "TREZO" only in headers)

**Voice:** Warm, calm, protective. Never hype. Never urgency.

**Forbidden phrases:**
- "Get rich quick"
- "Guaranteed returns"
- "Beat the market"
- "Smart money"
- "Crush it"

**Preferred phrases:**
- "Layer by layer"
- "Built to last"
- "Wealth that compounds"
- "Your treasure, protected"

---

## A Note on Origin

Trezo was built because the founder wanted to break a cycle — to create a tool that protects wealth the way maternal love protects a child. Not perfectly. Not always successfully. But always trying. Always layered.

Every line of code in this project should reflect that intent.

---

## END OF README

*For full project state and resume instructions, open `TREZO_MASTER_RESTORE.md`.*
