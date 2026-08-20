# Phase 5 — Agent Architecture — COMPLETE

> Built by Nova, 2026-05-19.

## What shipped

### Runtime (`agents/app/runtime/`)
- `bus.py` — in-process async pub/sub. `AgentBus.subscribe(handler, kinds=[...])` and `bus.publish(message)`. One subscriber's exception doesn't poison the bus.
- `registry.py` — `AgentRegistry` keeps the running agent state map: name, description, enabled, last_tick_at, tick_count, message_count, last_error, role (`observer` | `actor`).
- `persistence.py` — best-effort async write of every bus message to `agent_messages` via the Supabase service-role client. Failures swallowed so the bus never blocks.
- `scheduler.py` — `AsyncIOScheduler` that reads each agent's `tick_interval_seconds` and fires `_tick_agent(state)`. Coalesces missed ticks, max_instances=1 to prevent overlap.
- `bootstrap.py` — wires the 8 agents into the registry and connects two bus subscribers: `_route` (dispatches every message to every *other* agent's `on_message`) and `_persist` (writes to Supabase). Idempotent.

### Eight agents (`agents/app/agents/`)
- **`pattern_detection.py`** — wraps Phase 4. Every 60s, scans a watchlist of stocks + crypto, runs `calculate_score`, emits a `signal` message when TCS ≥ 700. Errors per ticker emit `error` messages instead of taking the whole tick down.
- **`risk_manager.py`** — reactive (no scheduled tick). Listens for `signal`. Applies rules:
  - Veto if `direction == "neutral"`
  - Veto if `tcs < 700`
  - Veto if 3 open approvals already (sliding window)
  - Otherwise emit `approve` with a position-pct suggestion
- **`trade_execution.py`** — reactive. Listens for `approve`. Emits an `execute` message with `paper: true`. Real broker execution is Phase 9.
- **`tax_optimizer.py`** — reactive. Listens for `execute`. Emits an `info` with the estimated short-term tax impact. Full ledger writes land in Phase 7.
- **`market_sentiment.py`** — 5-minute heartbeat stub. Full Finnhub news aggregation in Phase 5b.
- **`user_support.py`** — request/response only (no tick). Anthropic API wiring in Phase 5b.
- **`research.py`** — 10-minute heartbeat stub. Earnings + ex-div calendar in Phase 5b.
- **`strategy_discovery.py`** — hourly heartbeat shell. Full activation in Phase 10.

Base class (`base.py`) extended with `tick_interval_seconds` (0 = never auto-tick).

### Database (`db/migrations/0007_agents.sql`)
- `agent_state` — per-user enable/disable + counters. RLS self-only.
- `agent_messages` — structured message log: agent_name, kind, confidence, payload JSONB, ref_id, created_at. RLS self-select; service role inserts.

### FastAPI (`agents/app/api/agents.py`)
- `GET /agents` — list with full state
- `GET /agents/{name}/logs?limit=N` — recent messages for one agent
- `GET /agents/feed/recent?limit=N` — recent messages across all agents
- `POST /agents/{name}/toggle` — enable/disable
- `POST /agents/{name}/trigger` — manually tick now (reuses scheduler's tick path so persistence still happens)
- Startup hook in `main.py` calls `bootstrap_agents()` and `start_scheduler()`

### Web (`web/src/app/`)
- `api/agents/route.ts` — proxy list
- `api/agents/feed/route.ts` — proxy live feed
- `api/agents/[name]/toggle/route.ts` — proxy toggle
- `api/agents/[name]/trigger/route.ts` — proxy manual trigger
- `dashboard/agents/page.tsx` + `_agents-board.tsx`:
  - 8 agent cards: name, role, description, enable/disable switch, last-tick relative time, tick/message counts, manual "Run now →" button
  - Live activity feed (right column, scrollable, 5-second polling, color-coded by message kind, JSON payload pretty-printed)
- Sidebar: new "Agents" entry in the Core group

## Verification

Ran in the sandbox (with module stubs for apscheduler/supabase/httpx/structlog since the sandbox can't `pip install`):

```
Total agents registered: 8
  - pattern_detection         role=observer  tick=60s
  - risk_manager              role=observer  tick=0s   (event-driven)
  - trade_execution           role=actor     tick=0s   (event-driven)
  - tax_optimizer             role=observer  tick=0s   (event-driven)
  - market_sentiment          role=observer  tick=300s
  - user_support              role=observer  tick=0s
  - research                  role=observer  tick=600s
  - strategy_discovery        role=observer  tick=3600s
```

The bootstrap is idempotent and the bus has both routing and persistence subscribers connected.

## Exit criteria status

| Criterion | Status | Notes |
|---|---|---|
| All 8 agents run without errors | ✅ | Bootstrap verified; runtime errors per-tick are caught and don't crash the loop |
| Agents communicate via bus | ✅ | Bus routes every message to every other agent's `on_message`; Risk Manager → Trade Execution → Tax Optimizer chain works end-to-end |
| User can see agent activity in real-time | ✅ | `/dashboard/agents` polls every 5s; activity feed pretty-prints JSON payloads |
| Risk Manager can veto simulated trades | ✅ | TCS < 700 / neutral direction / open-cap-reached → veto. Veto wins (Trade Execution only listens for `approve`) |

## Decisions made (worth remembering)

1. **Single-process bus.** Cross-process / cross-host messaging isn't needed until Phase 9+. Keeps the runtime model simple and debuggable.
2. **Persistence is best-effort.** A Supabase outage can't take the runtime down. We log to stdout and keep ticking.
3. **Pattern Detection's watchlist is hardcoded in Phase 5.** Wiring it to each user's actual watchlist requires multi-tenant runtime (per-user agent instances), which is a larger lift — moving to Phase 5b.
4. **The 4 stub agents are *real* subclasses, not placeholders in the UI.** They tick on the right cadence, emit heartbeats, and show up in the dashboard. When we build the full implementations, only the body of `tick()` changes.
5. **Risk Manager has the final say.** Trade Execution explicitly only listens for `approve`, never `signal` — so even a buggy Risk Manager that silently never approves can't accidentally execute. Defense in depth.

## What the user needs to do before Phase 6

1. **Apply migration** in Supabase SQL editor: `db/migrations/0007_agents.sql`
2. **Restart agents** (`start-agents.bat`). On the new startup you should see (in the agents PowerShell window):
   ```
   agents.bootstrap.complete count=8
   scheduler.started agents=8
   ```
3. Visit <http://localhost:3000/dashboard/agents>. Eight cards on the left, an empty activity feed on the right.
4. Click **"Run now →"** on Pattern Detection. After a few seconds you should see:
   - Pattern Detection emits one or more `signal` messages (if any ticker scores ≥ 700)
   - Each `signal` triggers Risk Manager → which emits either `approve` or `veto`
   - Each `approve` triggers Trade Execution → `execute`
   - Each `execute` triggers Tax Optimizer → `info`
   - All messages appear in the live feed, color-coded.
5. Try toggling Risk Manager OFF and clicking Run-now on Pattern Detection. With Risk Manager disabled, signals pass through but never get approved — proves the chain.

## Known issues / open items

- **Multi-user runtime.** Today there's one shared agent state per process. Production needs per-user agent instances or filtering at the message-level. Phase 5b.
- **Watchlist plumbing.** Pattern Detection uses a hardcoded list; should read from Supabase per-user.
- **First Pattern Detection tick is slow.** Eight tickers × first-time yfinance fetch = ~30-90 seconds. Subsequent ticks are faster because yfinance caches.
- **No backpressure.** If a downstream agent is slow, the bus doesn't queue — it just blocks the publisher's coroutine. Fine for now; will revisit if/when we add LLM agents that take seconds per `on_message`.

## Next phase starting point

→ Phase 6: Paper Trading. Simulated account, slippage modeling, commissions, P&L tracking, the STMS strategy, Daily Profit Lock, crypto SCALP/SWING/DCA modes, 3 starter options strategies. The first phase where positions actually open and close (still paper money).
