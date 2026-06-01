# Trezo Platform

> **Layer by Layer. Trade by Trade.**

This is the build directory for the Trezo platform — a multi-layer automated wealth-building platform. Specifications live in `../TREZO_PROJECT/01_handoff_specs/`.

## Monorepo Layout

```
trezo-platform/
├── web/        Next.js 14 (App Router) + TypeScript + Tailwind + shadcn/ui
├── api/        Node.js + Express API gateway
├── agents/     Python 3.11 agents (FastAPI + APScheduler)
├── db/         Supabase migrations (SQL)
└── .github/    CI/CD workflows
```

## Quick Start

```bash
# 1. Install root tooling (workspaces use npm workspaces — no extra global needed)
npm install

# 2. Web app (Next.js 14)
cd web
npm install
cp ../.env.example .env.local        # fill in keys
npm run dev                          # http://localhost:3000

# 3. API gateway (Express)
cd ../api
npm install
cp ../.env.example .env              # fill in keys
npm run dev                          # http://localhost:8000

# 4. Python agents
cd ../agents
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8001
```

## Environment

Copy `.env.example` to `.env` (api, agents) and `.env.local` (web). See that file for each variable.

## Build Phases

See `../TREZO_PROJECT/01_handoff_specs/TREZO_PHASE_PLAN.md`. Phase checkpoints live in `../TREZO_PROJECT/05_for_claude_code/checkpoints/`.

## License

Private. All rights reserved.
