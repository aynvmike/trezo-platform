# Trezo Database

PostgreSQL schema for the Trezo platform, run via Supabase.

## How to apply

In the Supabase project SQL editor, run files in `migrations/` in numerical order:

1. `0001_initial_schema.sql` — core tables (profiles, watchlists, trades, agent_logs)
2. `0002_rls_policies.sql` — row-level security

Or via the Supabase CLI:

```bash
supabase db push
```

## Tables

- `profiles` — per-user settings (capital, risk tolerance, daily target, tax status)
- `watchlists` + `watchlist_items` — user watchlists with ethical-filter notes
- `trades` — immutable trade ledger (paper + real)
- `agent_logs` — every agent decision with reasoning
- `kindrip_children` + `kindrip_contributions` — Phase 8 child portfolios

`auth.users` is provided by Supabase. We never duplicate user identity.
