# Independent paper books — activation handoff

Mike authorized supported trading capabilities for every one of his separate
paper accounts on 2026-09-10. This change prepares that activation; it does not
establish that the running server or database has been updated.

## Changes

- Bearish pattern scoring and reward/risk geometry now mirror bullish evidence.
  Eligible strategies are compared in both directions; a held incumbent must
  pass current scoring and eligibility checks.
- Settings, adaptive scope, risk verdicts, execution limits, rotation quotas,
  options counters and broker routing belong to the individual book. Missing
  settings or account ownership cannot substitute the primary account.
- Options entry lanes and the dividend ladder use each book's controls. The
  Wheel UI, orders, reconciliation and permissions use the selected book.
- Agents show per-book capability reasons and scoped activity, including
  bearish option exposure. Market reports retain a durable opportunity journal
  with source, timestamp, direction, prerequisites and research results.
- Research can test bullish and bearish hypotheses against historical data.
  It cannot promote an unvalidated rule into an executable strategy.

## Apply in order

1. Apply `supabase/migrations/20260910143905_independent_book_capabilities.sql`
   to **Trezo**. New columns default off so schema installation does not enable
   other owners. Scope adjustments gain book ownership and owner-based RLS;
   historical adjustments without a book no longer control any account.
2. Deploy this code after both Python gates and the web checks pass. Keep the
   existing paper-only endpoints. On the Trezo host, run from the repository:

   ```powershell
   .\agents\.venv\Scripts\python.exe ops/enable_books.py --owner-id cf1b0460-039d-40ac-adc8-7ca3ef17c5bb
   .\agents\.venv\Scripts\python.exe ops/enable_books.py --owner-id cf1b0460-039d-40ac-adc8-7ca3ef17c5bb --apply
   ```

   Use the installed Python environment if its location differs. The first
   command previews the exact rows and runtime controls. Both commands verify
   all owned paper book mappings before writes. The apply command enables each
   own settings row and account, then verifies the result. It enables only
   matching runtime slots and preserves already enabled unrelated slots.
   Missing mappings or nonpaper endpoints stop activation. Existing numeric
   risk limits, capital allocations and halts remain authoritative.
3. Restart the agents service to load the runtime account list, and rebuild the
   web service. Confirm a fresh `engine_boot` from the new process and code
   revision. A completed relay job alone is insufficient deployment evidence.
4. Verify each book separately in Agents and Bot Tuning. Confirm its own broker
   permissions, capability reasons, equity, positions and activity. Check fresh
   scanner/risk/execute or veto receipts, including the book ID and reason.
   An enabled lane means eligible to evaluate trades, not a promise of fills.

The activation helper does not place an order, reset a halt, increase a numeric
risk limit or enable a real-money account. It enables existing adaptive behavior
within each book's controls; experimental research remains research.

## Retained unavailable capabilities

- Crypto shorts: no borrowing or derivatives execution adapter.
- FX: no execution venue connected.
- Bull-call debit spreads and butterflies: idea builders exist, but no
  autonomous selection branch is connected.
- Broker stock reevaluation: the existing leg resynchronizer rejects shorts
  and does not safely roll back failed broker changes. Protective exits remain
  active; this route remains unavailable until repaired and verified.
- Unmapped strategy-library cards and new research rules: retained as research
  references with reasons, without executable promotion.
- Broker-specific permission, collateral, liquidity, borrowing and data failures
  are evaluated separately for each book at entry time.

## Access status at preparation

The refreshed Supabase connector exposed only RealEstateCodex and
NomadicTravelGlobeTrek, not Trezo. No database migration, activation, server
restart or broker order was executed during this work. The exact Trezo project
URL or a corrected project connection is required to finish remote activation.
