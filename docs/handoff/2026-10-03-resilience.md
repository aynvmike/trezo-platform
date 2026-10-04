# Database independence and recovery preparation

The current incident is a hosted PostgreSQL disk-full recovery loop. Management
logs showed `53100`, failure to write `pg_wal/xlogtemp`, and repeated REST 503s.
A subsequent read-only SQL probe still received connection refused. This is
evidence of the database failure; it is not evidence of Alpaca rate limiting.

The existing deployment relay uses that same database. Publishing code does not
establish that the server pulled it or that the database recovered.

## Changes prepared

- Agent telemetry is committed to a bounded host SQLite outbox, then delivered
  with original timestamps and stable UUIDs. Per-book retry delays and quotas
  keep failures separate. Replay inserts telemetry only; it does not resubmit
  orders or replay the trading bus. `/health` exposes aggregate backlog/loss
  counters; `status: ok` remains process liveness, not trading readiness.
- Main execution refuses unknown allocation exposure, daily-dollar limits or
  this book's risk state. Direct income buys require verified settings and
  holdings/exposure; automatic options refuse a missing own-book risk state.
  Existing exit paths are unchanged.
- Watchdog flow checks separate books and identify explicit disabled-entry
  vetoes as settings decisions. Counts are window heuristics, not a substitute
  for order-by-order broker reconciliation.
- QA orders-snapshot incidents clear after a successful live orders read; a
  refresh failure is reported even when the full QA sweep is not due.
- `ops/host_preflight.ps1` reads host capacity and service facts without secrets.
  `ops/host_maintenance.ps1` provides manual deployment without Supabase, requiring
  an exact reviewed commit, staged guards, checkout ownership, and a fresh local
  boot beacon. Conflicting deployment activity prevents mutation or rollback of
  another operation's checkout. It does not install an automatic updater.
- `ops/self_host/README.md` documents complete recovery, isolated restore and
  cutover. Its tools compare preserved three-book identities and table contents.
  A matching inventory alone never authorizes cutover or new trading.

The queue retains up to 14 days, 5,000 rows/8 MiB per book and 20,000 rows/32 MiB
total. Its SQLite database is capped at 64 MiB; a transient rollback journal
uses additional bounded space. Expiry, capacity and write failures are visible
losses. This is outage buffering, not an indefinite archive or backup.

## Remaining operational work

1. Obtain an authenticated host administration session and run the preflight.
   The documented host is Windows Server 2022; its current spare resources and
   ability to host a Linux stack are unverified. Docker Desktop is unsupported
   on Windows Server. Do not install it or purchase a second host implicitly.
2. Recover the source or obtain a verified complete backup. Current application
   archives omit essential tables and cannot establish complete recovery.
3. Rehearse an isolated restore on a suitable Linux host. Verify Auth/RLS,
   Storage files, backups, all three books' settings and broker reconciliation.
4. Stop all competing writers, take a final export, update engine/API/web
   endpoints together, rebuild the web app, and verify one active engine.
5. Observe fresh runtime receipts and broker reads before calling the deployment
   or migration complete. Do not relax risk settings to produce fills.

No server installation, database migration, subscription change or live-trading
activation is represented by this code change. Profitability still requires a
complete broker audit with fees and enough independent observations; restoring
execution alone does not demonstrate an edge.

Follow-up before enabling income again: its direct accumulator still bypasses
RiskManager's computed kill-switch checks. The crypto-only configuration now
blocks that entry path even when settings are unavailable. Shared scanners can
also still perform unnecessary work when settings cannot be read; that is a
remaining load-reduction opportunity, not permission for an entry.
