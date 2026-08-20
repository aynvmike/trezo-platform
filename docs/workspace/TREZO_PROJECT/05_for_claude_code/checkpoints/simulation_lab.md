# Checkpoint — Simulation Lab

Date: 2026-05-26
Goal: stress-test harness — replay the agents across the user's
watchlist over a recent window at a chosen account size, end-to-end,
so we (and the beta testers) can see how the system behaves before any
real money is at stake.

## What changed
- agents/app/data/simulation_lab.py (new)
  - run_simulation(symbols, days, starting_equity, tcs_threshold,
    stop_pct, target_pct): per ticker, runs compare_strategies (every
    strategy scored, best one wins), keeps only the trades whose entry
    falls within the last `days` bars, stamps each with candle dates,
    sizes them at 25% of starting equity, applies them chronologically
    to build an equity curve.
  - Returns the full result the page renders: starting/ending equity,
    return %, per-symbol summary, by_strategy buckets, chronological
    trade list, equity_curve points.
- agents/app/main.py — new GET /simulation/run endpoint.
- web/src/app/api/simulation/run/route.ts (new) — auth-gated proxy that
  resolves the user's default watchlist server-side and forwards to the
  agents endpoint.
- web/src/app/dashboard/simulation/page.tsx (new) — server page; auth,
  loads watchlist, hands tickers to the lab.
- web/src/app/dashboard/simulation/_simulation-lab.tsx (new) — client
  component: preset window chips (5/7/14/30 days), preset equity chips
  ($1k/$5k/$10k/$25k/$100k), TCS input. Renders KPI tiles, SVG equity
  curve, by-strategy / by-ticker tables, and a chronological trade
  timeline with the "Why entered" column (TCS + dominant pattern).
- web/src/components/dashboard/nav-config.ts — Simulation Lab added to
  the core sidebar group, right after Backtest.

## Notes
- Trade sizing is a flat 25% of starting equity per position (no cash
  tracking, no slippage, no fees) — flagged in the page footer. This is
  for behaviour stress-testing, not P&L prediction.
- The strategy chosen per ticker mirrors the pattern_detection agent's
  per-stock selection: highest-traded strategy in the window wins.
- The Simulation Lab pairs naturally with the new "Reset paper account
  to $X" control on the Paper Trading page — pick the equity, run the
  sim, then reset the paper account to the same number to follow up
  live.

## Verified
agents py_compile OK; all 4 web files balanced 0/0/0.

## Still queued
- Alpaca Live wiring + go-live checklist (Mike asked for this last).
