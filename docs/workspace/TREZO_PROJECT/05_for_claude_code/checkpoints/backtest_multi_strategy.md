# Checkpoint — Multi-strategy backtest

Date: 2026-05-24
Feature: backtest every strategy, pick the best per symbol; show strategy
in the table; hover a trade to see why it was taken.

## What changed
- agents/app/backtest/engine.py
  - BacktestTrade now records entry_tcs + entry_pattern (the signal at
    the moment the trade opened).
  - New compare_strategies(symbol, candles, ...): runs all 6 strategies
    over one candle fetch, returns per-strategy results + best_strategy.
    "Best" = traded strategies, profit factor >= 1 preferred, then
    highest total return.
- agents/app/main.py
  - New GET /backtest/compare — fetches candles once, calls
    compare_strategies, returns {symbol, candles, strategies[], best}.
- web/src/app/api/backtest/compare/route.ts  (new)
  - Proxies /backtest/compare; persists only the winning strategy to
    backtest_runs (one row per symbol, not six).
- web/src/app/dashboard/backtest/_backtest-runner.tsx  (rebuilt)
  - New checkbox: "Test every strategy and keep the best one" (default ON).
  - Results table has a Strategy column (the chosen strategy per row).
  - Expanding a compared row shows a per-strategy scoreboard (all 6,
    "Best" badge) above the chart.
  - One-symbol + compare = full CompareView: ranked strategy table, tap a
    strategy to load its chart.
  - Watchlist summary shows the most-picked strategy across the list.
  - Trade chart dots have hover tooltips (TCS + pattern at entry, exit
    reason + P&L); trade table has a "Why it entered" column.

## Notes
- All files verified: agents py_compile OK; web files balanced 0/0/0.
- Compare runs 6x the scoring work per symbol — slower but one candle
  fetch; UI streams results and has a Stop button.

## Queued (from Mike's testing notes)
1. Site-wide beginner / pro setting, default beginner (Pattern Engine
   already has a 3-level toggle — make it global).
2. Agents pick the best strategy per stock when *trading*, not just in
   backtest — /backtest/compare is the foundation for this.
3. Help search should answer a typed question (AI), not keyword-filter.
4. Dividend Wheel: cycle state (sold put / waiting / assigned / covered
   call) + dividend & FPSL income + beginner explainer.
5. Future projections for every account, factoring taxes + the effect
   of tax-saving / donating — possibly its own section.
