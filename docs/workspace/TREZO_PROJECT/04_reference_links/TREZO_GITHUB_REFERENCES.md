# TREZO — GITHUB REPOSITORIES & EXTERNAL REFERENCES

## Purpose
External resources Claude Code should reference (not necessarily clone) during the Trezo build. Each entry includes why it's useful, what to extract, and how to use it efficiently.

---

## TIER 1 — DIRECTLY USEFUL (Reference While Building)

### 1. TauricResearch/TradingAgents
**URL:** https://github.com/TauricResearch/TradingAgents
**License:** Research / Apache 2.0
**Stars:** 70K+
**Why it matters:** Multi-agent LLM framework from UCLA/MIT researchers. Maps almost perfectly to Trezo's agent architecture.

**Agent mapping to Trezo:**
| Their Agent | Trezo Equivalent |
|---|---|
| Fundamentals Analyst | Research Agent (extended) |
| Sentiment Analyst | Market Sentiment Agent |
| News Analyst | Market Sentiment Agent |
| Technical Analyst | Pattern Detection Agent |
| Bull/Bear Researchers | NEW — debate layer worth adding |
| Risk Management Team | Risk Manager Agent (extended) |
| Trader | Trade Execution Agent |
| Portfolio Manager | NEW — coordinator role |

**What to extract for Trezo:**
- LangGraph orchestration patterns
- Bull/Bear debate dynamics (great addition to Trezo)
- Pydantic structured-output schemas
- Inter-agent communication patterns
- Memory log and decision tracking

**Reference, don't fork.** Pull patterns into Trezo's own codebase.

---

### 2. anthropics/financial-services
**URL:** https://github.com/anthropics/financial-services
**License:** Anthropic-managed
**Why it matters:** Official Anthropic plugins for financial workflows. Saves significant tokens by providing pre-built capabilities.

**Plugins to install in Claude Code:**
- `financial-analysis` — DCF, LBO, 3-statement models, comps
- `equity-research` — Earnings updates, investment theses, morning notes
- `wealth-management` — Portfolio analysis, risk assessment

**Built-in data connectors available:**
- Daloopa
- Morningstar
- S&P Global
- FactSet
- Moody's
- LSEG
- PitchBook

**How to use:**
```bash
# In Claude Code, after installing the marketplace:
/plugin marketplace add anthropics/financial-services
/plugin install financial-analysis@financial-services
```

**Token savings:** These plugins replace ~30-50% of what we'd otherwise build from scratch.

---

### 3. vaughanf1/BB-Terminal
**URL:** https://github.com/vaughanf1/BB-Terminal
**License:** AGPL-v3 (upstream OpenBB)
**Why it matters:** The "trading desk" the founder envisioned. Bloomberg-style terminal built on OpenBB Platform.

**What it provides:**
- 50+ data providers (Yahoo, FRED, Polygon, FMP, etc.)
- 270 endpoints
- Amber-on-black professional UI
- 16 Bloomberg-like functions (INTEL, OMON, CURV, WEI, etc.)
- Built-in signal rules engine

**Integration with Trezo:**
- Embed as the user's "Pro Terminal" view (Layer 7)
- Source: real-time charts, options chains, yield curves
- Doesn't replace Trezo — complements it as advanced data view

**Reference architecture:**
- React + TypeScript + Vite frontend
- TradingView lightweight-charts
- OpenBB Platform Python backend

---

### 4. anthropics/skills
**URL:** https://github.com/anthropics/skills
**License:** Apache 2.0 (most skills)
**Why it matters:** Official Anthropic skills repo. Reference for building Trezo's own skills.

**Pre-built skills useful for Trezo:**
- `pdf` — PDF generation (tax forms, reports)
- `docx` — Word doc generation (research memos)
- `xlsx` — Excel generation (financial models)
- `pptx` — Presentation generation (portfolio reviews)

**How to use in Claude Code:**
```bash
/plugin marketplace add anthropics/skills
/plugin install document-skills@anthropic-agent-skills
```

---

### 5. anthropics/claude-plugins-official
**URL:** https://github.com/anthropics/claude-plugins-official
**Why it matters:** Curated directory of trusted plugins. Browse for additional tools we might need.

---

## TIER 2 — INSPIRATIONAL (Look At, Don't Copy)

### 6. OpenBB Platform
**URL:** https://github.com/OpenBB-finance/OpenBBPlatform
**Why it matters:** The underlying data platform BB-Terminal uses. Free, comprehensive financial data layer.

**Could replace:**
- Finnhub (limited free tier)
- CoinGecko
- Multiple separate API integrations

**Consideration:** If we use OpenBB, we get 50+ providers in one library.

---

### 7. AI Hedge Fund n8n Workflow Pattern
**Source:** The transcribed video (in handoff)
**Why it matters:** Practical pattern for building personality-driven agents.

**Apply to Trezo's Strategy Discovery Agent (Phase 3):**
- Buffett personality → Value investing perspective
- Dalio personality → Macro economic analysis
- Wood personality → Innovation/growth focus
- Ackman personality → Activist/concentrated bets

When the Strategy Discovery Agent analyzes a position, it can run it through these personas to surface different viewpoints.

---

### 8. Various Bloomberg Terminal Clones (for UI inspiration)
- `jmrothberg/bloomberg-terminal` — Single-file browser clone (phosphor-green UI)
- `feremabraz/bloomberg-terminal` — Next.js 15 version with Redis caching
- `Chavithra/OpenBBTerminal` — Another OpenBB-based terminal

**Use:** UI design inspiration only. Trezo has its own Woven Basket aesthetic.

---

## TIER 3 — EDUCATIONAL (For the User, Not the Build)

### 9. anthropics/claude-cookbooks
**URL:** https://github.com/anthropics/claude-cookbooks
**Why it matters:** Jupyter notebooks showing how to use Claude effectively. Good for the User Support Agent.

---

### 10. anthropics/courses
**URL:** https://github.com/anthropics/courses
**Why it matters:** Anthropic's educational courses including prompt engineering.

---

## INSTALLATION ORDER FOR CLAUDE CODE

When Claude Code starts the Trezo build, install plugins in this order:

```bash
# Step 1: Add Anthropic-official marketplaces
/plugin marketplace add anthropics/financial-services
/plugin marketplace add anthropics/skills
/plugin marketplace add anthropics/claude-plugins-official

# Step 2: Install core financial plugins
/plugin install financial-analysis@financial-services
/plugin install equity-research@financial-services
/plugin install wealth-management@financial-services

# Step 3: Install document creation skills
/plugin install document-skills@anthropic-agent-skills

# Step 4: Reload plugins
/reload-plugins
```

After install, Claude Code has access to dozens of pre-built skills, saving significant build time.

---

## REFERENCE WORKFLOW

For each major Trezo component, here's which external reference to consult:

| Trezo Component | Primary Reference |
|---|---|
| Agent orchestration | TradingAgents (LangGraph patterns) |
| Pattern detection | User's Codex + TradingAgents technical analyst |
| Bull/Bear debate (Phase 3) | TradingAgents researcher agents |
| Risk management | TradingAgents risk team + Trezo's own rules |
| Trading desk UI | BB-Terminal (OpenBB) |
| Financial modeling | anthropics/financial-services |
| Document generation | anthropics/skills |
| Multi-personality analysis | AI Hedge Fund n8n video pattern |
| User support Q&A | claude-cookbooks examples |

---

## LICENSING NOTES FOR CLAUDE CODE

Be aware of license requirements:
- **TauricResearch/TradingAgents** — Research use, attribution required
- **OpenBB Platform** — AGPL-v3 (copyleft, affects derivatives)
- **anthropics/financial-services** — Anthropic-managed terms
- **anthropics/skills** — Apache 2.0 (permissive)

**Recommendation:** Trezo proprietary code stays Trezo's. Reference these repos for patterns and use their plugins, but don't fork the AGPL-licensed code into Trezo's main codebase.

---

## TOKEN-SAVING STRATEGIES

### Use plugins, don't rebuild
Every plugin we install is functionality we don't have to spec, build, debug, and maintain. The financial-services plugins alone save weeks of work.

### Reference patterns, don't reimplement
When Claude Code needs to build an agent, point it at the TradingAgents agent for inspiration rather than designing from scratch.

### Use cheaper models for routine work
- Sonnet for routine implementation
- Opus only for complex architectural decisions
- Haiku for simple repetitive tasks

### Enable prompt caching
Anthropic's prompt caching gives major discount on repeated system prompts. Critical for agent loops that run thousands of times.

### Phase-gate everything
Don't let Claude Code spread across phases. Complete Phase 0 fully before Phase 1 begins.

---

## PHASE 8 — ALPACA INTEGRATION REFERENCE

### Petersoj/alpaca-java
**URL:** https://github.com/Petersoj/alpaca-java
**License:** MIT  ·  **Stars:** 247  ·  **Latest:** v10.0.1 (2024)
**Why it matters:** A complete, well-maintained Java client for the Alpaca trading API — Trader API (orders, positions, account), Market Data API, Broker API, and websocket/SSE streaming. Provided by the founder as the Phase 8 Alpaca reference.

**IMPORTANT — Java, not Python.** Trezo's agents are Python, so this library cannot be dropped in directly. Use it as a *reference* for the Alpaca REST API surface (the library is generated from Alpaca's OpenAPI spec). Trezo calls the same REST API directly via httpx — see `agents/app/brokers/alpaca.py` (started in Phase 8a).

**What to extract for Phase 8b (Alpaca paper order execution):**
- Order placement: POST /v2/orders — symbol, qty, side, type, time_in_force; bracket orders with stop-loss + take-profit legs.
- Paper endpoint: https://paper-api.alpaca.markets (vs the live endpoint).
- Positions + account endpoints (already wired in Phase 8a).
- Trade-updates streaming pattern, for fill reconciliation.

**Python SDK alternative:** the official `alpaca-py` package. Trezo deliberately uses direct REST instead — lighter, async-native, consistent with how it already calls Finnhub/CoinGecko, and no extra dependency.

---

## CRYPTO STRATEGY REFERENCES (candidate strategies)

Provided by the founder as additional agent / strategy knowledge (2026-05-21).

### Grid Trading Bot — RECOMMENDED for the strategy library
**URL:** https://blockchain.oodles.io/dev-blog/build-grid-trading-bot/
**What it is:** Places a ladder of buy/sell limit orders across a price range (a "grid"). Each time a buy fills, a sell is placed one grid step above it, and vice versa — profiting from oscillation inside the range. Parameters: grid range (upper/lower), grid levels, grid step, order size, plus a stop-loss below the range.
**Fit with Trezo:** Strong. Grid trading is a recognized mean-reversion strategy that works best in choppy / range-bound markets — exactly the regime Trezo's Phase 7.5 regime classifier already detects. A natural addition to the Strategy Library and the crypto bot. Candidate work: a `grid_trading` StrategyCard + a grid mode in the crypto strategy module.

### Solana Sniper Bot — NOT recommended for the core product
**URL:** https://blockchain.oodles.io/dev-blog/how-to-build-a-solana-sniper-bot/
**What it is:** Buys brand-new token launches on Solana DEXs the instant they list, aiming to flip them quickly.
**Fit with Trezo:** Poor. Sniping new token launches is high-risk speculation heavily exposed to memecoins and rug-pulls. It conflicts directly with Trezo's design — the ethical filters, the protection-ring model, the "reject weak trades" core principle, and especially the protected inner layers and the KINDRIP children's portfolio. Nova's recommendation: do not add this to the core product. If ever explored, it must be a fully isolated, opt-in, clearly-warned experimental module outside the protection rings — never wired into the paper engine's main flow.

---

### alpacahq/cli — official Alpaca CLI (hands-on tool, not a code dependency)
**URL:** https://github.com/alpacahq/cli
**License:** Apache-2.0  ·  **Language:** Go  ·  Alpha preview
**What it is:** Alpaca's own command-line tool for the Trading API — submit orders, list positions, read account equity, check the market clock, pull data. Explicitly "built for agents" and automation; paper trading is the default.
**Fit with Trezo:** A useful *hands-on tool for Mike*, not a code dependency. It is a standalone Go binary, so Trezo's Python agents do not call it — Trezo talks to the same Alpaca REST API directly (faster, no extra binary to install). Handy for Mike to verify his Alpaca paper account from a terminal: `alpaca account get`, `alpaca position list`, `alpaca clock`, `alpaca doctor`. It also cross-confirms the order shape Trezo's Phase 8b uses (`POST /v2/orders`).

---

## END OF GITHUB REFERENCES
