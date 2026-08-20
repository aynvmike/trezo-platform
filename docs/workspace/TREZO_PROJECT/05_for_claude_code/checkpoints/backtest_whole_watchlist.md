# Checkpoint — Backtest a whole watchlist

Date: 2026-05-24
Feature: backtest every ticker on a watchlist at once (was: one ticker at a time)

## What changed
- web/src/lib/watchlists.ts
  - Added listWatchlistsWithTickers(userId): returns every watchlist with
    its tickers attached (2 queries total). Used by the backtest page.
- web/src/app/dashboard/backtest/_backtest-runner.tsx  (rebuilt)
  - New mode toggle: "A whole watchlist" vs "One symbol".
  - Watchlist mode: pick a list, runs every stock/crypto sequentially,
    streams results in live, with a "Stop" button to cancel mid-run.
  - Options on a list are skipped (not directional stop/target trades).
  - Results: summary cards (avg return, avg win rate, best, weakest) +
    a per-ticker table; tap a tested row to expand its price chart +
    simulated trades. One-symbol mode unchanged in behaviour.
- web/src/app/dashboard/backtest/page.tsx
  - Seeds the default watchlist, loads all watchlists with tickers,
    passes them to BacktestRunner. Intro copy refreshed.

## Notes
- No agents-side change. Each ticker still calls /api/backtest, which
  proxies the agents /backtest endpoint and persists the run, so a
  watchlist run also populates "Recent backtests".
- All three files verified balanced 0/0/0.

## Still queued from Mike's testing notes
1. Help search should answer a typed question (AI), not keyword-filter.
2. Dividend Wheel: show cycle state (sold put / waiting / assigned /
   covered call), count dividend + FPSL income, beginner explainer.
3. Future projections for every account, factoring taxes + the effect
   of tax-saving / donating — possibly its own section.
