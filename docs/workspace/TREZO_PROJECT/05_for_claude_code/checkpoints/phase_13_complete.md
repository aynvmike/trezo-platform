# Phase 13 — Agent shared & evolving memory

Date: 2026-05-23
Status: COMPLETE

The user asked for the agents to have evolving memory and to share
information with each other. Until now agents only passed transient
messages on the bus — nothing carried forward between ticks or restarts.

## Built

- **Migration 0024 — `agent_memory` table.** Columns: agent, scope
  ('shared' = all agents read; else the owning agent), topic (the
  upsert key), category, content, weight, timestamps. RLS: signed-in
  users may read it (the dashboard shows it); only the service-role
  agents write.

- **agents/app/runtime/memory.py** — the store:
  - `remember()` — writes or REINFORCES a memory. Keyed by
    (agent, scope, topic): a repeat updates the content and bumps a
    `weight` instead of duplicating. That is the "evolving" part — a
    repeated observation grows more confident.
  - `recall()` / `recall_shared()` — read memory, most-reinforced and
    most-recent first.
  - `prune()` — trims the store beyond a soft cap.
  - Best-effort: with no Supabase, every call is a safe no-op.

- **agents/app/agents/base.py** — the Agent base class gained
  `remember()` and `recall()`. So all 17 agents now have evolving
  memory and can read the shared pool — the capability is universal.

- **strategy_discovery.py — the first rich user.** Each hourly run it
  now: recalls the shared memory pool; writes a `warning` memory for any
  strategy running at a net loss; and — learning from the Phase 12d
  `backtest_runs` log — computes which strategy variant has the
  strongest average backtested return and remembers it as a shared
  `insight`. Reinforced every run, so the signal sharpens over time.

- **web Agents page** — a new "What the agents have learned" section
  shows the shared memory: each insight, which agent wrote it, its
  category, and its reinforcement weight. Stale copy fixed ("eight
  agents" → 17; "observe-only" → paper-trading).

## Scope note

The memory *capability* is now available to every agent via the base
class. Strategy Discovery is the first to use it richly (write + read +
learn from backtests). Wiring more agents to write their own
observations is incremental follow-up work — the infrastructure and the
shared pool are in place now.

## Verification

- All 79 agent files parse clean (ast sweep).
- memory.py, base.py, strategy_discovery.py parse clean.
- Web Agents page brace/paren/bracket-balanced.

## User-side steps

- Apply migration 0024_agent_memory.sql.
- Restart the agents service and the web app. The learned-memory
  section on the Agents page fills in as Strategy Discovery runs
  (hourly) and as backtests accumulate.
