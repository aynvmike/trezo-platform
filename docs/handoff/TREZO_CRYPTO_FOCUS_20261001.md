# Crypto focus and audit — 2026-10-01

Mike requested crypto only, a working version of Claude's ledger audit, and
verification that the engine actually receives market data. At 16:37 UTC he
said "Send now", authorizing immediate deployment during market hours.

## Observed before repair

- The configured Supabase project is reachable through the connector.
- Hosted engine logs were current. Last recorded boot: `376fce1` on September 18.
- All three broker book mappings were paper accounts. Personal holdings/watchlists
  were excluded from the settings change.
- Crypto was enabled. Crypto reevaluation settings were false. The old deployed
  version still uses environment gates; changing these DB columns alone cannot
  enable reevaluation until the newer per-book implementation is deployed.
- At 16:21 UTC the preceding 24h included 1,162 crypto approval events, 4
  submission events, 1,907 already-held refusals and 1,493 pocket-capacity refusals.
  These are event counts, not a deduplicated signal conversion funnel.
- Both larger books had only two crypto slots. `real_cost` observations showed
  Alpaca bid/ask data in the running scanner, but `observe_only=true`.
- `book_daily_pnl` was empty. No broker-confirmed edge was established.

## Applied settings

At 16:25:28 UTC, for the three verified paper books only: disable pattern, STMS,
extended, wheel, day options, spreads, long options and dividend entry switches;
set stock/options/income/forex budgets to zero. Crypto budgets remain unchanged. Risk fractions, loss controls and existing
position exits were not changed. The private before/after snapshot is excluded
from this public repository.

The running engine subsequently submitted ETH, DOT and XRP for each larger book.
Six corresponding ledger rows have distinct Alpaca order IDs, from 16:26:02 through
16:27:46 UTC. This demonstrates execution after the slot restriction was removed;
it does not establish net profitability or independently reconcile each fill.

## Code in this repair

- `ops/ledger_audit.py`: crypto-only, read-only, stdlib. Entire account fill history
  is loaded before filtering completed entry orders by close date. Matched partial
  realized totals are separately filtered by their actual exit timestamps. There
  is no fabricated short position for an unmatched sale. Decimal FIFO; both-side
  notionals; one sample per fully closed entry order, not per partial fill.
- Date-cluster bootstrap; minimum 50 completed entry orders across 10 closing dates.
  PASS is exploratory paper evidence, not proof of live edge. Multiple comparisons,
  serial dependence across dates and overlapping orders still limit inference.
- `INCOMPLETE` on missing basis, duplicate pages, capped pagination, unreadable
  positions, coin-denominated fee quantities, inventory adjustments or inventory
  mismatches. Coin fees need receipt-level reconciliation; the tool does not invent
  an allocation. Cost assumptions are explicit: 25 bps fee + 5 bps extra slippage
  per side, configurable locally. Actual fee postings are not subtracted twice.
- Optional `--ledger` keeps user/book and strategy groups separate and does not
  label their unreconciled P&L as broker truth. Missing P&L stays missing.
- `crypto_entry.py` is called by the actual Alpaca crypto entry method. It requires
  finite, valid bid/ask with a timezone-aware timestamp no more than 120 seconds old
  (up to 5 seconds of future clock skew); rejects absent/stale/crossed quotes; sizes
  at ask; refuses a target that does not exceed measured spread plus existing fee
  assumption and 5 bps additional slippage per side. Checks freshness again before
  submission after intervening reads. Quote evidence accompanies the ledger payload.
- Explicit zero allocation is refused in per-book admission, including generic
  stock strategies. Missing allocations retain posture behavior. Existing exits
  remain on their own paths. Alpaca spot crypto entry path refuses shorts.
- `ops/diag.py`: use the actual schema names `agent_name`, `quantity`, `args`.

## Run without a laptop

After the new engine boots, queue the existing `report_status` kind with exactly:

```json
{"crypto_audit_since":"2026-07-24"}
```

This takes the detached worker path and runs the fixed audit on the server using
host-held credentials. The result contains compact per-book summaries under 8,000
characters. It places no orders, changes no settings, accepts no command/path,
and requests no restart. A done task means collection returned; inspect each
book's verdict and issues, especially fee-in-kind and basis coverage.

Local commands:

```sh
python ops/ledger_audit.py --selftest
python ops/ledger_audit.py --since 2026-07-24 --ledger
python ops/ledger_audit.py --input broker_export.json --since 2026-07-24
```

PowerShell env override uses `$env:TREZO_ENV = 'C:\Trezo\trezo-platform\agents\.env'`.
Hosted environment variables work without a file. Exit 2 means incomplete/error;
exit 0 means collection completed, not that profitability was established.

## Rollout verification

Run both `python -m tests.run_all` and pytest in the existing dependency-equipped
environment. Never skip the deployed gate. Confirm a new engine boot at the merge
commit, then request the hosted audit. Verify fresh entry quote refusals/evidence
and per-book crypto reevaluation events before claiming those repairs are active.
The new quote gate can reduce submissions when quotes are stale or targets cannot
cover costs; it does not manufacture more winning trades.
