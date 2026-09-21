# Day-trade income implementation — Nova review

Implements the September 21 handoff on `codex/day-trade-income-20260921`, based on main `5c8e0f3` (after PR #3 / `7096970`). Goal lock ships ON. This is code and offline verification, not deployment or evidence of profitable trading.

## Behavior and reachable call sites

All three entry controls run after already-held detection and before capacity in the per-book fanout at `agents/app/agents/trade_execution.py:801`.

| Change | Audible event | Call site |
|---|---|---|
| Full-exit re-entry requires both 90-minute cooldown and movement outside the lane cost band; fresh sided quote | `reentry_refused` | `trade_execution.py:902` |
| Intraday stock PDT guard uses own-book cached account and fresh submission recheck | `pdt_guard` | `trade_execution.py:920`, submission check `:1461` |
| PDT-worded broker rejection does not increment reject-storm count | `pdt_reject` | `trade_execution.py:1644`, `:1769`, `:2046` |
| Persistent daily goal lock from shared account counter; entry-only | `goal_locked`, `goal_lock_refused` | `agents/app/paper/entry_discipline.py:178`, `trade_execution.py:923` |
| Nightly receipt report and morning scorecard | bus events `receipt_pnl`, `receipt_pnl_scorecard` | `agents/app/runtime/scheduler.py:176`, `agents/app/agents/market_desk.py:184` |

The three refusal spellings are deliberate outcomes in the existing watchdog. Nightly events are bus messages; the durable evidence is the Markdown and database scorecard. Shared monitor classification avoids separate strategy lists. Options PDT phase-in, exits, risk limits and capacity limits retain their existing behavior. Missing required reads fail closed or yield unknown.

## Migration and activation

Migration: `supabase/migrations/20260921152142_day_trade_income.sql`. Adds default-ON per-book setting, persistent goal latches and service-written `book_daily_pnl` rows. `enable_books.py` previews the switch without overwriting an existing per-book opt-out.

The goal latch observes every shared realized-counter update, so a hit followed by giveback before the next entry stays locked, including across restart. It resets with the existing UTC account rollover. The trigger function is private, constrained to the account update row and uses an empty search path. Its definer privilege preserves existing RLS-authorized owner account updates while the latch table stays service-only. The public observation RPC is service-only and security-invoker. Scorecards have owner-scoped authenticated reads and service-only writes. No historical rows are rewritten.

Nova owns review and deployment. PR #3 activation remains a separate pending sequence: its migration → main deployment through the relay → `enable_books.py` preview/apply after Mike's go. Apply the income migration before deploying this runtime. Follow the handoff's outside-09:30–16:00 ET deployment rule. Never start a second engine. Verify a new `engine_boot` beacon with deployed commit, new PID and `agents=30`; a successful pull job alone is insufficient.

## Receipt report interpretation

Each nightly report covers the previous 21:30 ET through current 21:30 ET, with adjacent windows covering overnight crypto without gaps. Day-trade labels independently mean entry and exit on the same ET calendar date. Goal accounting still follows the existing UTC rollover.

FIFO matches use broker fills and actual quantities/prices, aggregate partials by entry/exit order pair, and assign strategy only from the matching entry order ID. Posted order fees take precedence; otherwise crypto uses 26 bps per side, explicitly `fee_source=model`. Reads bind each book separately and submit no orders.

Unknown opening basis, incomplete pages, unsupported option settlement effects and unallocated fees remain visible. Totals cover known FIFO matches, not an invented complete return. FILL receipts contain no bid/ask; measured spread and fees-plus-spread friction stay unknown. Fee share is reported separately. Exact equity reconciliation requires aligned prior/current snapshots and cash flows; the first run may lack these. Daily portfolio history remains evidence with an explicitly unaligned reference comparison, not a fabricated reconciliation residual. Unknown metrics are stored as NULL, not zero.

No first nightly files or live-book results were produced in this workspace: host credentials/laptop bridge are still pending. From the Trezo repository root on the configured Windows host, run once without starting the engine:

```powershell
.\agents\.venv\Scripts\python.exe .\agents\scripts\run_receipt_pnl.py --date 2026-09-20
```

The date labels the completed window ending at 21:30 ET on that date. The command processes all configured books and writes `C:\Trezo\reports\pnl-<account_id>-2026-09-20.md` plus one database row per book/day. It exits nonzero if any book is partial/unknown or none are configured. An incomplete first reconciliation is expected until an aligned baseline exists; inspect the reasons rather than treating missing evidence as zero.

## Verification and outstanding acceptance

- Bare deployment gate: `cd agents && python3 -m tests.run_all`; 86 suites, floor 85, zero activity-log writes.
- Full pytest: `cd agents && python3 -m pytest tests -q`.
- SQL/RLS integration: install `@electric-sql/pglite@0.5.8` in a temporary tooling directory, then run `PGLITE_MODULE=/absolute/path/to/node_modules/@electric-sql/pglite/dist/index.js node db/tests/day_trade_income.mjs`.
- SQL checks exercise persistent giveback/restart/rollover behavior, book isolation, default ON, service writes, owner reads, denied public writes/RPC calls, and the existing owner account-update path.
- Receipt fixtures exercise all three bound books, failed reads, partial fills, shorts/options multipliers, fees, reconciliation gaps, overnight coverage, unknown persistence and write confirmation.

Still pending on the host: Nova review/deploy, the activation sequence, first three reports, and one measured session confirming refusal reasons. Ten measured sessions are required before evaluating the handoff's scaling targets; this PR makes no earnings guarantee.
