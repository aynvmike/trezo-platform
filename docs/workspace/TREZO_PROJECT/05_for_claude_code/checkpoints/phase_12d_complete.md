# Phase 12d — Backtest upgrade

Date: 2026-05-23
Status: COMPLETE

Fourth part of the Phase 12 UX overhaul. The user reported the backtest
did not work with all strategies, and asked that it accept new strategy
variants the agents can learn from.

## What was wrong / what changed

1. **Crypto could not be backtested.** The endpoint only used
   `fetch_stock_candles`. Fixed — `agents/app/main.py` `/backtest` now
   detects crypto symbols (COIN_MAP) and pulls ~1 year of CoinGecko
   OHLC; stocks still use ~2 years of daily bars.

2. **The strategy list was incomplete** — the page offered only 3
   strategies (default, stms, orb). It now offers all six directional
   strategies: default, pattern, stms, orb, crypto, extended. The
   scorer already handles any strategy name (unmapped ones fall back to
   flat scoring), so all six work. Options and Dividend Wheel are not
   directional stop/target trades — the page says so and points to
   paper trading for those.

3. **Strategy variants** — the endpoint now accepts custom `stop_pct`
   and `target_pct` (clamped to sane ranges). The page exposes Stop %
   and Target % inputs, so a user or agent can test a variant of a
   strategy, not just the fixed 5/10.

4. **Runs are persisted — the agents' learning substrate.** New
   migration 0023 adds `backtest_runs` (RLS: a user owns their rows;
   the service-role agents can read all). The `/api/backtest` proxy
   writes a row after every successful run. The backtest page now shows
   a "Recent backtests" table; the runner calls router.refresh() so it
   updates immediately. Phase 13 (agent evolving memory) will consume
   this table so the agents actually learn from the history.

## Files

- agents/app/main.py — crypto-aware fetch + stop/target params.
- db/migrations/0023_backtest_runs.sql — new table + RLS + index.
- web .../api/backtest/route.ts — pass stop/target, persist the run.
- web .../dashboard/backtest/_backtest-runner.tsx — 6 strategies,
  Stop %/Target % inputs, refresh on completion.
- web .../dashboard/backtest/page.tsx — Recent backtests table.

## Verification

- agents/app/main.py parses clean (ast).
- All web files brace/paren/bracket-balanced.
- No node_modules in the sandbox — no tsc run.

## User-side steps

- Apply migration 0023_backtest_runs.sql.
- Restart the agents service and the web app.
