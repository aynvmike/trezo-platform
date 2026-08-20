# Checkpoint — Market Horizons (cross-asset awareness)

Date: 2026-05-26
Goal: the agents see the whole market, not just the user's watchlist.

## What changed
- agents/app/data/markets_horizon.py  (new)
  - compute_snapshot(): pulse + 30-day correlations across six asset
    proxies: SPY (stocks), BTC (crypto), GLD (gold), UUP (USD/Forex),
    TLT (bonds), JEPI (income ETFs — same family as REX FEPI/NVDY/MSFY).
  - summarise_snapshot(): one plain-language sentence about today.
  - Pairs surfaced: Gold/USD, Crypto/USD (the Forex–crypto family),
    Bonds/Stocks.
- agents/app/agents/market_horizon.py  (new)
  - MarketHorizonAgent — ticks every 15 minutes, emits an info message
    summarising who leads and whether the classic relationships hold.
- agents/app/runtime/bootstrap.py — registers the agent as an observer.
- agents/app/main.py — new GET /markets/pulse endpoint backed by the
  same compute_snapshot helper.

- web/src/app/dashboard/markets/page.tsx  (new) — Market Horizons page:
  asset-class pulse (6 cards with sparklines), cross-asset relationship
  cards (correlation strength + the two sparklines side by side), and a
  vehicles explainer (annuities, bonds, REX-style income ETFs, futures,
  ETF rebalancing, forex & cross-asset hedges).
- web/src/components/dashboard/nav-config.ts — added Market Horizons to
  the core sidebar group.
- web/src/lib/agent-message.ts — friendly label for `market_horizon`.

## Why this matters
Mike: "I want the agents to be aware of the entire market and the
possibilities of strategies… I do not want to limit the possibilities."
The page makes that explicit: it shows the broader landscape, names the
relationships the agents now read (Forex/Crypto, Gold/USD, Bonds/Stocks),
and surfaces vehicles a new trader may not know exist — annuities not
as a liability but as an investment vehicle; bonds; covered-call REX-
style income ETFs; futures (deferred — same family as Options); ETF
rebalancing (rotation within a theme).

## Verified
- agents compile (markets_horizon.py, market_horizon.py, bootstrap.py,
  main.py).
- Web files balanced (nav-config.ts, agent-message.ts, markets/page.tsx).

## Still queued
- Dividend Wheel: cycle state + dividend & FPSL income + explainer.
- Future projections for every account, factoring taxes — own section.
