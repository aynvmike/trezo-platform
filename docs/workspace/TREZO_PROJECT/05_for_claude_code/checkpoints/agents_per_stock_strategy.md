# Checkpoint — Agents pick the best strategy per stock (trading)

Date: 2026-05-24
Goal: solidify the trading agents before launch — the watchlist
scanner now chooses the best strategy per stock, not one for all.

## What changed
- agents/app/strategies/selector.py  (new)
  - select_strategy(candles, ctx, history, strategies): scores a stock
    under every eligible strategy, picks the strongest read. Long-only:
    prefers bullish; drops strategies with a net-loss backtest history
    on that stock; highest live TCS wins, backtest history breaks ties.
  - eligible_strategies(asset_type, window flags): window-bound
    strategies (STMS / ORB / Extended) drop out when their window is
    closed, so the bot never picks a strategy that cannot trade now.
  - Returns the pick + the full "considered" comparison + a plain
    reason string.
- agents/app/agents/pattern_detection.py  (rebuilt)
  - For each watchlist ticker: scores it under every eligible strategy
    via select_strategy and emits the signal under the winner.
  - Loads per-ticker backtest history from backtest_runs (cached 15
    min) — the quality gate. The user's watchlist backtests now feed
    live strategy selection.
  - Signal payload carries strategy + strategy_selection {chosen,
    reason, considered}.
- web/src/lib/agent-message.ts
  - Signal lines now name the chosen strategy: "Signal on AMD — looks
    bullish (confidence 780) · best fit: Pattern Engine."

## How it flows
pattern_detection picks strategy -> signal tagged with it ->
risk_manager approves -> trade_execution already reads `strategy`
(sets GTC bracket for extended, allocation bucket, attribution).
No change needed downstream — verified market_type_for handles all
strategy names (stock strategies -> "stocks" bucket).

## Verified
- selector.py + pattern_detection.py + engine.py + main.py compile.
- FULL import of app.agents.pattern_detection verified: imports clean,
  PatternDetectionAgent() instantiates, every wired symbol resolves,
  window helpers callable. (httpx + pydantic_settings stubbed for the
  test since this sandbox has no network — only external libs stubbed,
  all Trezo code ran for real.)
- New permanent test: agents/tests/test_strategy_selector.py — 9 tests
  covering window gating + the select_strategy contract; all pass.

## Scope note
The specialist scanners (STMS, ORB, Crypto, Extended) stay as dedicated
single-strategy hunters on their own universes. Multi-strategy selection
applies to pattern_detection — the agent that trades the user's
watchlist.

## Queued (from Mike's testing notes)
1. Site-wide beginner / pro setting, default beginner.
2. Help search should answer a typed question (AI), not keyword-filter.
3. Dividend Wheel: cycle state + dividend & FPSL income + explainer.
4. Future projections for every account, factoring taxes — own section.
