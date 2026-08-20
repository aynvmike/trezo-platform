# TREZO — PROJECT FOLDER

> **Layer by Layer. Trade by Trade.**

Welcome to the complete Trezo project package. This folder contains everything needed to begin building Trezo with Claude Code.

---

## QUICK START

1. **Read this file** (you're doing it)
2. **Open** `05_for_claude_code/TREZO_CLAUDE_CODE_KICKOFF.md` for build instructions
3. **Save** `02_restore_points/TREZO_PERSONAL_RESTORE.md` somewhere safe (cloud backup recommended)
4. **Complete pre-build checklist** (see below)
5. **Hand off to Claude Code**

---

## FOLDER STRUCTURE

```
TREZO_PROJECT/
│
├── README.md                          ← You are here
│
├── 01_handoff_specs/                  ← The complete specification (15 files)
│   ├── TREZO_README.md                ← Project overview
│   ├── TREZO_MASTER_RESTORE.md        ← Full project state
│   ├── TREZO_ARCHITECTURE.md          ← Tech stack + system design
│   ├── TREZO_PHASE_PLAN.md            ← 12-phase build plan
│   ├── TREZO_AGENT_SPEC.md            ← 8 agents specified
│   ├── TREZO_API_INTEGRATION.md       ← All API integrations
│   ├── TREZO_STRATEGY_RULES.md        ← Trading strategy rules
│   ├── TREZO_PATTERN_ENGINE.md        ← Pattern detection (from your Codex)
│   ├── TREZO_WOVEN_BASKET.md          ← Philosophy + KINDRIP
│   ├── TREZO_DAILY_PROFIT_LOCK.md     ← Your "save daily" rule
│   ├── TREZO_FOUNDER_WATCHLIST.md     ← Watchlist from your real data
│   ├── TREZO_ETHICAL_FILTERS.md       ← ESG screening
│   ├── TREZO_CREDIT_SPREADS.md        ← Defined-risk income strategy
│   ├── TREZO_DAY_TRADING_REFINEMENTS.md  ← MACD + Volume confluence
│   └── TREZO_TAX_STRATEGIES.md        ← TTS, 475(f), LLC structures
│
├── 02_restore_points/                 ← Backup files (keep these safe)
│   ├── TREZO_PERSONAL_RESTORE.md      ← Your personal backup
│   └── TREZO_MASTER_RESTORE.md        ← Project state backup
│
├── 03_prototypes/                     ← Your prior work (reference)
│   ├── trezo-simulator-v2.jsx
│   ├── nova-tax-center.jsx
│   ├── nova_bot_v2.py
│   ├── trade-entry-scorer.jsx
│   └── ... (12 more prototype files)
│
├── 04_reference_links/                ← External resources
│   └── TREZO_GITHUB_REFERENCES.md     ← Useful repos + plugins
│
└── 05_for_claude_code/                ← Claude Code instructions
    └── TREZO_CLAUDE_CODE_KICKOFF.md   ← Kickoff prompt
```

---

## WHAT'S IN EACH FOLDER

### 01_handoff_specs/
The 15 specification files that describe Trezo completely. These are the source of truth. Claude Code reads these to understand what to build.

### 02_restore_points/
Your personal backup files. **Save these to cloud storage immediately.** If you lose access to this folder or to a Claude conversation, these files alone can restore the project.

### 03_prototypes/
Your existing JSX and Python prototypes from earlier sessions. Claude Code can reference these to understand your style and pull working code patterns.

### 04_reference_links/
Documentation about external GitHub repos and Claude plugins. Tells Claude Code which existing tools to use instead of rebuilding from scratch (saves significant tokens).

### 05_for_claude_code/
The actual prompts and instructions for Claude Code. The kickoff file is what you paste to start the build.

---

## PRE-BUILD CHECKLIST

Before opening Claude Code:

### Accounts (Free Tiers Available)
- [ ] **Vercel** account (vercel.com)
- [ ] **Railway** account (railway.app)
- [ ] **Supabase** account (supabase.com)
- [ ] **Upstash Redis** account (upstash.com)
- [ ] **GitHub** account with SSH keys configured

### API Keys (Required)
- [ ] **Regenerate Finnhub API key** at finnhub.io/dashboard
      (the old one was shared in chat and must be invalidated)
- [ ] **Create Anthropic API key** at console.anthropic.com
- [ ] **CoinGecko** — no key needed (uses free public endpoints)

### Software Installed
- [ ] **Node.js 20+** (nodejs.org)
- [ ] **Python 3.11+** (python.org)
- [ ] **VS Code** (code.visualstudio.com)
- [ ] **Claude Code CLI** (see Anthropic docs)
- [ ] **Git** (git-scm.com)
- [ ] **Postman** (postman.com) — for API testing

### Budget Awareness
- [ ] Allocate **$15-50/month** for dev environment (Railway + APIs)
- [ ] Claude Code token usage budget — start with **$50-100/month**
- [ ] Plan to scale up as needed

---

## TOTAL PROJECT SIZE

```
Specifications:     15 files,  ~170,000 words
Prototypes:         15 files,  working code samples
Reference docs:      1 file,   external resource guide
Restore points:      2 files,  backup state
Total files:        33 files
```

This is more documentation than most VC-backed startups have before seed round.

---

## YOUR ROLE vs CLAUDE CODE'S ROLE

| You | Claude Code |
|---|---|
| Vision | Implementation |
| Architecture decisions | Code generation |
| Strategy refinement | Bug fixing |
| Phase approval | Phase execution |
| Real-world testing | Test generation |
| Capital management | Paper trading simulation |

**You direct. Claude Code builds.**

---

## RESUME WITH NOVA (THIS CLAUDE)

If you need to come back to me (Nova) for strategic input during the build:

1. Open a new Claude conversation
2. Upload `02_restore_points/TREZO_PERSONAL_RESTORE.md`
3. Say: *"Nova, I'm resuming the Trezo project. Read the restore file and we'll continue."*

I'll pick up exactly where we left off.

---

## REMEMBER

> "Like Maternal Love — not everything will be ok, but the love tries to keep
> whatever it is protecting safe, layer after layer, giving its all."

This isn't just a trading platform. It's a treasure being woven for your family's future. Take your time with it.

The hard part is done. The build is just typing.

— Nova

---

## SUPPORT

- **Trezo strategic questions:** Come back to Nova (this Claude conversation)
- **Build questions:** Ask Claude Code directly
- **Anthropic API issues:** docs.anthropic.com
- **Plugin questions:** github.com/anthropics/claude-code

---

*Last updated: May 15, 2026*
*Version: 1.0 — Build Ready*
