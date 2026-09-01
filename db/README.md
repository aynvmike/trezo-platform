# Trezo Database

PostgreSQL schema for the Trezo platform, run via Supabase.

## How to apply

Migrations are applied **by hand**: paste each file, whole, into the
Supabase project SQL editor and run it, in numerical order. There is no
Postgres password on the laptop or the server, so no agent or script can
run DDL for you — only Mike, in the editor.

Since `0058_schema_migrations_and_lane_mode.sql` there is a ledger:

```sql
select version, applied_at, assumed from public.schema_migrations order by version;
```

Rows with `assumed = true` predate the ledger and were inferred, not
witnessed. Every migration from 0058 on records itself at the end of the
file (`insert into schema_migrations ... on conflict do nothing`), so
"did 00NN run?" is a SELECT. Follow that convention in new files.

Conventions for a new migration:

- Number it next in sequence; one concern (or a small named set) per file.
- A header comment that says WHY, naming the audit finding or date.
- Idempotent where Postgres allows: `if not exists`, `drop policy if
  exists` then `create policy` (there is no `create policy if not
  exists`), existence checks in `do $$ ... $$` blocks before `revoke` /
  `alter function`.
- Wrap in `begin; ... commit;` when a partial application would be worse
  than none (0047, 0059, 0060 do this).
- Record itself in `schema_migrations`.

Files ending in `DIAGNOSTIC_*.sql` are read-only queries, not migrations.

### Pending as of 2026-09-01

- `0059_quantity_scale.sql` — QP-01: `quantity` on `paper_positions`,
  `trades`, `trade_outcomes` widens from `numeric(20,8)` to
  `numeric(30,12)` so 9-decimal Alpaca crypto fills stop being rounded.
- `0060_security_authz.sql` — AUTH-03/04/05. **Run the commented
  "RUN FIRST" query at the top of the file before applying it**: it lists
  any `trading_accounts` row whose `owner_id` is not an `auth.users` id.
  The migration refuses (and rolls back) if any exist.

## Tables (by lineage)

- `profiles` — per-user settings (capital, risk tolerance, daily target,
  tax status). A PERSON.
- `trading_accounts` (0045/0047) — the account directory: which BOOKS
  exist and which person owns each. Every book table's `user_id` is an
  `account_key` here, not an `auth.users` id. Credentials are never
  stored here; they live in `agents/.env` by slot.
- `paper_accounts`, `paper_positions`, `paper_vault_transactions` —
  the paper book: cash/counters, open and closed positions, vault moves.
- `trades` — immutable trade ledger (paper + real). Append-only.
- `trade_outcomes` (0032+) — the learning ledger: one row per close with
  entry context + outcome. The learning loop reads this, not
  `paper_positions`.
- `options_positions` (0012) — option legs. As of the 2026-09-01 audit
  the real option book also lives in `paper_positions` rows with
  `asset_type='option'`; which table is the ledger of record is an open
  decision (see `docs/workspace/DEFERRED_ITEMS_TRACKER.md`).
- `bot_settings` — per-book behaviour (posture, lanes, floors, lane mode).
- `watchlists` + `watchlist_items` — user watchlists with ethical-filter notes.
- `agent_logs`, `agent_messages`, `agent_state` — every agent decision
  with reasoning; the engine-only message bus copy; per-agent state.
- `kindrip_children` + `kindrip_contributions` — Phase 8 child portfolios.
- `ops_*` (0040, 0050, 0052–0056) — watchdog alerts, relay tasks,
  heartbeat config/state, log tail, briefings.
- `schema_migrations` (0058) — the ledger above.

`auth.users` is provided by Supabase. We never duplicate user identity.

## Row-level security

Every user-facing table has RLS on. Book tables use
`user_id in (select public.my_account_keys())` (0047) so a person sees
all of their books; person tables use `(select auth.uid()) = user_id`.
The engine writes with the service-role key, which bypasses RLS. The
web tier serves users with the anon key plus their session; the web
SERVER additionally holds the service-role key for exactly two machine
routes (`/api/internal/broker-token`, `/api/cron/refresh-broker-tokens`,
via `web/src/lib/supabase/admin.ts` — AUTH-01/02, 2026-09-01). It never
reaches the browser. (Reviewer fix R-README-1.)

## One-off data tools

- `agents/tools/unwind_phantom_pnl.py` — reverses the 2026-08-28
  phantom-close P&L (audit PH-2/PH-5). Dry run by default; `--apply`
  only after Mike's approval. Never deletes; originals are kept under
  `source_payload.phantom_unwind` / `entry_payload.phantom_unwind`.
