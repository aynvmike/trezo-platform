# Broker fill accounting repair

Prepared September 18, 2026. Code and local tests only: the remote database
connection is read-only, so neither migration nor runtime deployment has occurred.
No broker orders or historical accounting corrections were performed.

## Problem and resulting behavior

Some broker-managed exits used candle prices or assumed an accepted order had
filled. Missing broker holdings and calendar expiry could also close ledger rows
without settlement evidence. Those paths could report profits or losses that did
not match the broker, and account counters could disagree with position outcomes.

The repair makes stock, crypto, and single-leg options closes depend on actual
cumulative broker order receipts. Durable database claims precede submission;
unknown submission responses stay pending instead of being retried blindly.
Confirmed fill deltas, position slices, outcomes, receipt deduplication, and
realized counters commit in one transaction. Broker cash continues to come from
the account snapshot; exit proceeds are not added a second time.

Stock and crypto decisions require fresh, sided Alpaca quotes. Entry records use
confirmed fill prices when available, including measured crypto fees paid in
coins. Pending entries retain explicit provisional basis metadata. Unknown fees
and historical entry costs remain provisional rather than silently verified.
Merging an entry preserves concurrent exit claims with a compare-and-set update.

Exit helpers verify the exact paper book and actual inventory before submitting.
A full-symbol liquidation requires the broker quantity to match the ledger row.
Duplicate managers or conflicting receipt ownership block ambiguous accounting.
Options and stock/crypto receipt consumers lock the same account before claiming
an order, preventing the two ledgers from consuming it independently.

Pending orders are polled before price availability is considered. Partial fills
reduce only confirmed inventory. A `done_for_day` order stays pending; terminal
receipt polling is idempotent. Profit-step recovery counts distinct broker orders,
not the number of partial receipt polls. An unreadable history remains unknown.

Broker-backed options no longer settle from a calendar date or current underlying
price. Missing expiry/assignment evidence is flagged for reconciliation. Expiration
day positions remain eligible for active management. The legacy day-options path
retains the existing indicative-feed policy and requires a fresh valid quote for
new submissions; indicative quotes never establish an accounting fill.

The broker snapshot endpoint now reports an unavailable book as unavailable.
The new standalone export reads all configured paper books without starting the
agent runtime and preserves failed or incomplete reads as unknown.

## Installation order

1. Review the branch and pass the deployment gates below in the target environment.
2. Use a migration-capable connection to apply, in order:
   - `db/migrations/20260918155909_broker_close_receipts.sql`
   - `db/migrations/20260918160730_option_close_receipts.sql`
3. Verify both versions in `public.schema_migrations` and the service-role RPC
   grants. The migrations are transactional, use invoker functions and restrict
   receipt tables/RPCs to the service role. They widen account P&L counters to four
   decimal places without reducing the available integer digits.
4. Deploy the reviewed runtime through the normal host procedure. Capture its
   boot commit and verify a tick for each configured book. Missing receipt RPCs
   block new broker exit submissions; deploy the database changes first.
5. Export broker evidence and reconcile existing discrepancies before claiming
   historical P&L is repaired. Do not reset account baselines or overwrite old
   losses with current quotes. Keep cash flows, resets, fills, fees, assignments,
   and changes to cost basis separate in that reconciliation.

The migration filenames were created with Supabase CLI 2.117.0. These changes do
not increase position caps, bypass the kill switch, or change the risk budget.

## Verification

From the repository root, using the project's Python environment:

```bash
cd agents
python -m tests.run_all
python -m pytest -q
cd ..
PGLITE_MODULE=/path/to/@electric-sql/pglite/dist/index.js node db/tests/broker_close_receipts.mjs
PGLITE_MODULE=/path/to/@electric-sql/pglite/dist/index.js node db/tests/option_close_receipts_test.mjs
```

The standalone deployment gate discovers at least 80 suites and must report zero
activity-log writes. The two SQL suites use PGlite 0.5.8 and each pass 14 actual
PostgreSQL integration cases, including rollback after a downstream write fails,
partial fills, deduplication, delayed fees, book isolation, cross-ledger ownership,
and role grants. Sequential claim collisions are covered; concurrent connections
are not simulated by PGlite.

Final local result: the deployment gate passed all 80 suites with zero activity-log
writes; pytest passed 1,243 tests. Both SQL suites passed all 28 combined cases.
Pytest reported one existing Supabase dependency deprecation warning.

## Broker evidence export

Run on the configured Windows host from the repository root:

```powershell
.\agents\.venv\Scripts\python.exe .\agents\scripts\export_broker_audit.py --after 2026-09-01T00:00:00Z --output broker-audit.json
```

The command performs GET requests only against Alpaca's paper endpoint. It exports
timestamped account balances, holdings, open/recent orders, activities including
cash movements, and portfolio history. It checks that the configured three books
return distinct broker identities; this does not independently prove that each
credential was assigned the intended book label. Identifiers are hashed and no
credentials are exported. Treat the financial report as private; do not commit it
to the public repository. Existing output files are never overwritten.

Exit codes: `0` complete, `1` incomplete evidence, `2` configuration/export error.
The default window is 24 hours. Missing values stay null, pagination exhaustion
marks the report incomplete, and no account return is inferred from a guessed
starting balance. The reads span a time window, not a single atomic snapshot.

## Remaining operational work

Actual historical losses and the other books' current equity still require host
broker evidence. Existing incorrect outcomes are not rewritten by these migrations.
Unlinked submission timeouts, ambiguous holdings, and expired/assigned contracts
without receipt evidence need explicit reconciliation. Automatic expiry/assignment
settlement booking is not implemented by this repair. Pending entries and unknown
entry fees can still leave P&L provisional. A green test run is not evidence of a
deployed fix or profitable trading.
