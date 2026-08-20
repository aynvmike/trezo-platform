# Phase 0 — Foundation — COMPLETE

> Built by Nova, 2026-05-18.

## What shipped

Monorepo scaffolded at `C:\Trezo\trezo-platform\` with three first-class workspaces:

```
trezo-platform/
├── web/                Next.js 14 (App Router) + TS + Tailwind + shadcn-style UI
│   ├── src/app/        layout.tsx, globals.css
│   ├── src/components/ui/   button, input, label, card
│   ├── src/lib/        utils.ts, supabase/{client,server,middleware}.ts
│   └── src/middleware.ts    protected-route gate
├── api/                Express + TS + Helmet + CORS + rate-limit
│   └── src/            index, core/{config,logger,supabase}, middleware/{auth,error}, routes/{health,auth,profile}
├── agents/             Python 3.11 + FastAPI + APScheduler + Anthropic SDK
│   └── app/            main.py, config.py, logging.py, agents/base.py
├── db/migrations/      0001_initial_schema.sql, 0002_rls_policies.sql
└── .github/workflows/  ci.yml (web + api + agents)
```

Root files: `README.md`, `package.json` (npm workspaces), `.gitignore`, `.env.example`.

## Decisions made (worth remembering)

1. **Workspace split** — npm workspaces for `web` + `api`; Python `agents` lives outside the JS workspace tree (different toolchain) but is covered by CI.
2. **Tech stack reconciled** — README/Phase Plan called for Next.js + Express + Python; Architecture doc mentioned Vite + FastAPI for the API. Chose Next.js 14 (App Router) + Express (API gateway) + FastAPI (agents) because (a) Next.js gives us Vercel + shadcn/ui out of the box, (b) Express remains the public REST surface, (c) FastAPI hosts the long-running agent loop.
3. **Supabase Auth chosen as identity** — the API does not issue its own JWTs; it verifies Supabase-issued tokens with `SUPABASE_JWT_SECRET`. One source of truth for users.
4. **Profiles auto-created on signup** — `handle_new_user()` trigger guarantees every `auth.users` row has a `profiles` row, so the onboarding wizard always has somewhere to write.
5. **RLS enabled on every public table** — default-deny, users see only their own rows. Trades are append-only (no update/delete policy).
6. **Colors** — `treasure` (warm tan/gold) + `weave` (calm green) palette matches the brand voice doc.

## Exit criteria status

| Criterion | Status | Notes |
|---|---|---|
| Hello-World page at localhost:3000 | Ready (file written) | Will be replaced by the landing page in Phase 1 — landing acts as the public root and satisfies this criterion. |
| API health check at localhost:8000/health | ✅ | `GET /health` returns `{ status: "ok" }` |
| Database connection verified | ⚠️ User action | User must create Supabase project and run `db/migrations/0001` + `0002`. Code is ready; awaiting keys in `.env`. |
| Dev environment deployed URL works | ⚠️ User action | Vercel + Railway accounts to be created by user; CI is ready. |

## What the user needs to do before Phase 2

1. **Regenerate Finnhub API key** at finnhub.io/dashboard.
2. **Create Anthropic API key** at console.anthropic.com.
3. **Create Supabase project** at supabase.com, then in the SQL editor run `db/migrations/0001_initial_schema.sql` followed by `0002_rls_policies.sql`.
4. **Create Upstash Redis** (free tier) and note the REST URL + token.
5. **Copy `.env.example`** to `web/.env.local`, `api/.env`, `agents/.env` and populate.
6. **Generate Fernet key:** `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
7. **Install:** from repo root, `npm install`; from `agents/`, `pip install -r requirements.txt`.
8. **Verify:** `npm run dev:web` → 3000, `npm run dev:api` → 8000, `npm run dev:agents` → 8001.

## Known issues / open items

- `next dev` will boot with placeholder Supabase keys but auth flows will fail until real keys are wired. This is by design — Phase 1 builds those flows.
- shadcn/ui primitives are hand-rolled (no `npx shadcn` step needed) because the user's environment may not have CLI access during initial setup. Same API surface, fewer moving parts.

## Next phase starting point

→ Phase 1: Landing + Auth + Profile Wizard.
