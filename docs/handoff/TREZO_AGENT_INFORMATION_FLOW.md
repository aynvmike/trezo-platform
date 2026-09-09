# Trezo: information for agents before terminal visuals

September 9, 2026. This is a code-level overview; it contains no production account or runtime audit results.

## Current change

Market Desk retains a valid fresh relay report when available. Otherwise, a bounded fallback requests SPY and QQQ together from the existing Alpaca snapshot adapter. Both symbols need valid completed minute bars and current-day provider bars. The view records feed and observation timestamps and expires after five minutes from its oldest observation. The desk polls every two minutes; polling does not renew source age.

Its direction label is explicitly a benchmark-price-versus-provider-daily-VWAP proxy. It does not supply news, social sentiment, VIX, market-wide breadth or movers. Existing consumers keep their risk limits. IEX is a limited feed rather than consolidated market coverage. [Alpaca market-data FAQ](https://docs.alpaca.markets/us/docs/market-data-faq), [snapshot API](https://alpaca.markets/learn/snapshot-api).

Research reads gain request-scoped failure categories with response bodies and exception text excluded. Concurrent reads remain separate. This improves diagnosis; it does not repair an external connection or replace missing equity with a guessed value.

## Feedback loop still needed

The completed-day observer retains evidence and hypotheses. Faithful replay adapters must connect those hypotheses to their actual strategy rules and relevant instruments. Historical exploration, untouched later evaluation and forward paper comparison must remain distinguishable. Automatic hypothesis replay and strategy promotion are not implemented by this update.

Progress should be assessed through reconciled net performance, costs, drawdown and independently evaluated improvements. There is no fixed daily profit quota. No-trade periods can remain appropriate under the existing policy.

## Visibility and validation

A compact operational view can show source age, last successful read, candidate under test, rejection reason and qualified results. A Bloomberg-style interface can follow later. Bloomberg's integrated data/news/analytics model is useful inspiration; this fallback does not reproduce that coverage. [Bloomberg Terminal](https://professional.bloomberg.com/products/bloomberg-terminal/).

Local synthetic validation passed 73 guard suites and 1,099 pytest tests. Deployment, actual data availability and profitability remain separate checks. This work introduces no paid subscription, new dependency, live broker connection or order-submission path.
