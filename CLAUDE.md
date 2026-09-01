# CLAUDE.md — Trezo platform

You are working on **Trezo**, a multi-agent automated trading platform owned by Mike.
This file is the standing briefing. Two companion documents carry the rest:

- `docs/handoff/TREZO_CONTEXT_EXPORT.md` — **the full context dossier.** Every incident,
  decision, open question and house rule accumulated across months of sessions. Read it
  before your first substantive change. It exists so you never have to ask Mike for
  background.
- `docs/handoff/TREZO_AUDIT_BRIEF.md` — the ordered audit Mike is asking for right now.

## What Trezo is

A Python agent engine (30 registered agents on a message bus) that scans markets,
proposes signals, risk-gates them, and routes approved ones to Alpaca (paper) or an
internal crypto paper engine — plus a Next.js dashboard and a thin Express API.
Three books (`primary`, `acct2`, `acct3`) trade independently against separate Alpaca
paper accounts. Supabase (Postgres + RLS) is the database and auth.

Repo layout is **npm workspaces**: root `package.json` declares `["web","api"]`.
Run ONE `npm install` at the repo root — never inside `api/` or `web/`.
Empty `api/node_modules` and `web/node_modules` are expected (everything hoists).

## Non-negotiable rules

1. **The deploy gate is `agents/tests/run_all.py`, NOT pytest.** `run_all` imports each
   `tests/test_*.py` and calls `_bootstrap.run_tests` on its namespace: plain `test_`
   functions, NO fixtures, no pytest, no `.env`, no network. A guard suite using a pytest
   fixture WILL roll the deploy back (it did, to commit 34b8065). Run both gates locally
   before pushing: `python3 -m tests.run_all` (the one that decides) and pytest.
   **Green pytest is not green deploy.**

2. **Every book is its own book.** No cross-book interference of any kind — a condition on
   the primary account must never change behaviour on another. Any state, gate, counter,
   cache, settings read or halt not keyed by `user_id`/book is a defect. This is a
   future-stakes rule: the account set will someday include a retirement account.

3. **A broker read that fails must never read as empty.** `get_positions()` collapsing a
   429/timeout into `[]` is indistinguishable from a flat account, and destructive logic
   downstream will close everything. Use `get_positions_strict()` (returns `None` on
   failure) anywhere the result can trigger an action. This lesson has been learned three
   separate times; do not learn it a fourth.

4. **BUILT BUT NOT BOUND is the house failure mode.** Code that exists, passes tests, and
   is never reached. Verify by grepping CALL SITES and checking what values actually
   arrive — never by reading a diff or a docstring. Ask of every guard: *when did this
   last fire?*

5. **A green deploy is not a working fix.** After shipping anything meant to repair an
   observable live symptom, watch the server log until the symptom STOPS
   (`ops/relay.py log --minutes N | grep ...`) before calling it fixed.

6. **Never fabricate a reconciliation.** A reconciler that guesses produces phantom fixes
   harder to find than the drift they replace. Close only the unambiguous case; flag
   everything else for a human.

7. **Trading mode is `paper`.** `TRADING_MODE=live` is inert — the live executor does not
   exist. Do not wire it. `GO_LIVE_CHECKLIST.md` gates that work.

## Where things are

| Thing | Path |
|---|---|
| Agent engine entry | `agents/app/main.py` |
| Agent wiring / bus / registry | `agents/app/runtime/bootstrap.py` |
| The 30 agents | `agents/app/agents/*.py` |
| Strategy logic | `agents/app/strategies/*.py` |
| Broker adapters + routing | `agents/app/brokers/*.py` |
| Ledger / paper engine / killswitch | `agents/app/paper/*.py` |
| Deploy gate | `agents/tests/run_all.py` |
| Deploy/restart relay | `ops/relay.py` |
| Dashboard (Next.js 14 App Router) | `web/src/app/**` |
| API gateway (Express) | `api/src/**` |
| DB migrations (0001–0058) | `db/migrations/*.sql` |
| Strategy specs | `docs/strategy/*.md` |
| Historical working docs | `docs/workspace/**` |

## Environment facts

- Working copy: `C:\Trezo\trezo-platform` on the laptop `Mike-2MM-Trezo`.
  `D:\Trezo` is a USB backup only — never the working copy.
- Remote: `https://github.com/aynvmike/trezo-platform`, branch `main`.
- Secrets live in three git-ignored files: `agents/.env` (~49 keys), `api/.env`,
  `web/.env.local`. GitHub has the code, never the secrets. `.env.example` lists key
  names. A one-time Alpaca + Supabase key rotation is still owed (older USB backup passes
  carried real keys).
- The dashboard is NOT public. It runs 24/7 as the `TrezoWeb` service on the server,
  reachable over Tailscale at `http://100.115.119.32:3000/dashboard`.
  `api.trezo.app` appears in an old spec — it is aspirational, nothing is deployed there.
- Supabase DDL cannot be run by an agent (no Postgres password). Migrations are pasted by
  Mike into the SQL editor; `schema_migrations` records what ran (since 0058).

## Windows gotchas on this machine

1. PowerShell execution policy blocks npm's `.ps1` shim — use `npm.cmd`, or launch
   scripts as `powershell -ExecutionPolicy Bypass -File ...`.
2. Python venv activation does not stick — always call
   `.\.venv\Scripts\python.exe -m pip ...` by full path.
3. A PowerShell window opened before an install keeps the old PATH. Reopen it.
4. npm 11 blocks install scripts by default and approvals are version-pinned; a lockfile
   bump silently re-blocks. After re-approving, `npm rebuild <pkg>`.
5. `npm run` must be issued from `C:\Trezo\trezo-platform`. `ENOENT package.json` means
   wrong directory, not a broken install.
6. Copying a repo mid-git-operation carries live `.git` lock files. Sweep `*.lock` when no
   git is running. `"Everything up-to-date"` after a FAILED commit is misleading — confirm
   with `git log --oneline`.

## How Mike works

Call him Mike. Be concise and direct; minimal formatting; prose over bullet-lists in
chat. Do not create Word/PowerPoint/Excel/PDF files unless he asks. Scale effort to the
task. When something is a decision rather than a defect, surface it and let him decide —
several are listed as HELD FOR MIKE in the context export and must not be resolved
unilaterally.
