# Checkpoint — Backtest polish + explainers + beginner-only sweep

Date: 2026-05-26

## What changed
- web/src/app/dashboard/backtest/_backtest-runner.tsx
  - New STRATEGY_DESC map + stratDesc(v) helper — plain-language
    descriptions for Default / Pattern / STMS / ORB / Crypto / Extended.
  - New fmtPF(pf, trades) + pfTooltip(pf, trades) — renders "—" for
    zero trades, "∞" for the 999 sentinel ("every trade was a winner —
    nothing to divide by"), and a tooltip explaining each case.
  - WatchlistRow, StrategyBreakdown and MetricsGrid all use the new
    formatter and tooltip — no more naked 999.00.
  - Strategy column cells get a title tooltip with the strategy's
    description so hovering "Default" tells you what Default is.
- web/src/app/dashboard/backtest/page.tsx
  - New beginner-only "What each strategy means" disclosure with all
    six strategies described in plain words.
  - New beginner-only "Profit factor — how to read 0.50, 1.50, ∞"
    disclosure explaining the ratio with examples.
- web/src/components/dashboard/scanner-pulse.tsx
  - When the strongest read is BEARISH, surface that explicitly in
    amber: "Trezo is long-only by default, so a bearish read does not
    become a trade. Lowering TCS alone will not change this." This
    matches what Mike saw — CSCO bearish at 670, lowering TCS to 670
    still wouldn't fire a long.
- 18 dashboard pages tagged with `beginner-only` on the intro
  paragraph (agents, budget, crypto, extended, help, kindrip, live,
  options, paper, performance, dashboard root, settings/bot,
  settings/filters, settings/profile, stms, stocks, strategy, tax).
  Beginner/Pro toggle now visibly changes content on every page.

## Verified
All 19 touched files balanced 0/0/0.

## Open items from Mike's note
1. "TCS / loss % settings didn't seem to affect the paper trader" —
   the Scanner pulse should now make this self-explanatory: settings
   change immediately, but a trade only fires when the next tick has a
   BULLISH read above your threshold. With CSCO bearish, no amount of
   TCS lowering helps; he needs the watchlist to throw a bullish read.

2. "Can it use the Alpaca API key instead?" — Alpaca IS already used
   for stock paper trades (trade_execution routes to Alpaca paper when
   ALPACA_API_KEY is set). What is NOT yet wired: Alpaca being the
   single source of truth for the paper-account dashboard (cash,
   equity, positions). That is the "Alpaca paper account mirror"
   build — a real next step:
     - new endpoint /api/paper/alpaca-snapshot returning cash, equity,
       positions from Alpaca's /v2/account + /v2/positions
     - Paper Trading page reads from Alpaca when alpaca_configured()
       instead of the internal paper_accounts row
     - reconciler to keep our internal ledger in sync for the slower
       parts (KPIs, vault, etc.)
