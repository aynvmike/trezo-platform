# Trezo: information for the agents before terminal visuals

September 9, 2026. Mike's priority is market-responsive trading and eventual income, with no fixed daily profit quota. A rich terminal interface is optional. This document distinguishes verified runtime evidence, changes prepared for review, and work still needed.

## What was verified

The connected engine logged a September 9 14:05 UTC boot at commit `5fd0c12`, with 30 agents. Research receipts at 14:06 showed four completed restricted-rule trials for each of three paper books. These receipts reused the day's persisted experiments; they do not represent 12 new experiments on every hourly tick or establish profitable trading.

The next research receipts, at 15:07 UTC, were blocked by `research_equity_read_failed`. Nearby broker logs show `ConnectTimeout` failures on account reads and other read endpoints across books. This supports a broker connectivity problem; the historical generic research receipt cannot establish the exact exception for its own request. Failed broker reads must not be interpreted as empty accounts, replaced by another book's balance, or hidden by a stale equity value.

Market Desk's newest ingested `market_context` briefing was dated August 28. No persisted Market Desk receipt was found by the read-only query. The desk's 24-hour report freshness rule therefore prevents that old briefing from providing current context. This does not mean every scanner lacks market data: other paths already read candles, quotes, market bias and company news directly.

The completed-day review is in draft PR #1; it was not part of that engine boot. No authenticated broker-data request was made from this workspace, and no trade or production database write was performed for this work.

## Minimum useful information flow

| Layer | Purpose | Current boundary |
| --- | --- | --- |
| Market observations | Prices, timestamps, spread, volume, volatility and scheduled events with identifiable sources | Existing adapters have different failure/provenance semantics; a successful request alone does not establish fresh or complete data. |
| Market Desk | Give consumers a shared, qualified current market view | The new internal fallback supplies only SPY/QQQ benchmark direction, using existing market-data access. It is not an all-market/news terminal. |
| Account state | Correct book, equity, funds available, positions, orders and receipts | Research reads current bound paper-broker equity. Unknown remains blocked. Equity is not identical to spendable buying power. |
| Strategy research | Create bounded hypotheses, retain all tests and identify failed ideas | Restricted rule composition is running. Historical research cannot automatically reach order execution. |
| Trade review | Inspect recorded outcomes and eligible sampled trade progress | PR #1 reviews seven completed UTC accounting days; recorded P&L is not a verified account return. |
| Feedback replay | Test an evidence-linked hypothesis using the actual strategy's rules and relevant instrument | Still missing: faithful adapters, versioned source-to-test requests and an appropriate future evaluation window. |
| Paper progression | Compare frozen candidates with the incumbent and suspend deterioration | A general candidate promotion/controller path is not implemented. |

## Internal Market Desk fallback

The review branch adds `app/knowledge/internal_market_context.py` and connects it directly to `MarketDeskAgent.tick`. A valid fresh relay briefing retains precedence. When none exists, the desk can request both SPY and QQQ in one existing Alpaca market-data snapshot request with an explicit feed. The desk polls every 120 seconds; the fallback is bounded to regular New York equity-session observations, allowing the last completed minute to remain useful only within its short source TTL after the close. This is roughly 195 batch requests over a full regular session when relay context remains absent; restarts and failures can change that count.

Both benchmarks must have valid, finite prices, current-session daily observations and recent completed minute bars. The source timestamps govern freshness; polling time cannot make stale data new. The internal view expires after five minutes from its oldest benchmark observation, independently of the longer report TTL. A missing symbol, malformed or stale response, future timestamp or failed request produces an unavailable receipt instead of a fabricated view.

The classification is explicitly a benchmark-direction proxy: both benchmark prices below their provider current-day bar VWAP indicate the risk-off proxy, both above indicate the risk-on proxy, and a split is mixed. The provider's daily-bar trade inclusion is not independently reconstructed as a regular-session VWAP; the previous daily bar is also provider-reported, and its freshness bound is not a verified exchange-calendar calculation. This threshold is a deterministic context convention, not an independently established predictive strategy. Existing consumers may apply their existing caution; this change does not lower risk thresholds, change position budgets, submit orders or promote candidates.

No VIX, market-wide breadth, movers, economic events or news sentiment is invented from these two benchmarks. Feed and source timestamps accompany the view, and unavailable categories remain identifiable. IEX coverage is limited to that feed; it is not the consolidated market. [Alpaca market-data FAQ](https://docs.alpaca.markets/us/docs/market-data-faq)

Alpaca documents snapshot responses containing minute and daily bars and supports requesting multiple symbols together. The fallback uses this existing capability, not a new subscription or external report generator. Market-data entitlements, quotas and infrastructure costs still apply. [Snapshot API](https://alpaca.markets/learn/snapshot-api)

This fallback is polling, not a streaming or low-latency execution system. Company-news classification remains on its existing separate path. A future event-driven feed needs timestamped, deduplicated events and explicit source quality; installing a terminal UI does not supply that contract.

## Research read diagnostics

The review branch adds request-scoped, sanitized failure detail for the account read that supplies research equity. Its purpose is to distinguish a connection timeout, HTTP failure, invalid account response and other failed reads without incorrectly attaching an older or concurrent request's error. It does not raise timeouts, retry indefinitely, infer balances or fix the external network connection itself. Deployed receipts must confirm the behavior before diagnosing later failures from them.

## Closing the strategy feedback loop faithfully

Daily review hints and ordinary SPY research currently run next to each other. Passing a losing options or crypto strategy name into the stock breakout backtester would not retest that strategy. Hints can also group several instruments under one strategy name, while a giveback hint proposes trailing or partial exits that the present core does not implement.

The next connection should load book-scoped immutable review evidence and partition it by strategy version, instrument, asset class and side. Each supported replay adapter must specify its entry/exit rules, timeframe and costs. Unsupported hypotheses need an explicit reason, not a generic unrelated backtest. Deduplicate by relevant source evidence and adapter/policy version; keep corrections, superseded requests and all attempted variants.

Register and freeze the candidate plan before evaluating later data. The losses that prompted a change may already lie inside the existing historical validation window; using those outcomes to tune and then calling the same window independent validation would leak information. Earlier replay should remain exploratory, followed by untouched later evidence and forward paper comparison.

A new strategy may lose to the incumbent. Missing data, costs exceeding the possible edge or a risk limit can make waiting the appropriate action. Desired income does not justify relaxing these checks. Verified profitability requires reconciled fills and fees plus cash-flow-adjusted account performance, including open positions and losses; neither a high win rate nor someone else's copied winning trades establishes it.

## Terminal and visibility

Bloomberg's useful model here is integrated data, news and analytics. Its documentation describes those capabilities; it is not a claim that acquiring them guarantees profitable trading. [Bloomberg Terminal](https://professional.bloomberg.com/products/bloomberg-terminal/)

Trezo can expose a compact operational view first: current feed age, last successful account read, candidate under test, rejection or waiting reason, actual paper position and verified/unknown result. Existing agent receipts and versioned research artifacts supply a starting point. A Bloomberg-style visual reconstruction and any paid data purchase are outside this change.

No new plugin is required for the bounded fallback or diagnostic work. The immediate constraints are information reaching the correct consumer, broker connectivity, faithful strategy evaluation and outcome accounting.

## Verification and deployment

Local September 9 checks passed: `python -m tests.run_all` ran 73 suites with zero activity-log writes; `python -m pytest -q` passed 1,099 tests. Fifteen new context tests cover the actual Desk-to-risk-consumer path, incomplete/malformed data, source freshness, same-timestamp corrections, relay precedence, overflow rejection and Windows timezone fallback using existing `pytz`. Four new capital-read tests exercise actual HTTP parsing with mocked transport, same-book concurrency, prior-error isolation, deadline reporting and cancellation.

The workspace tests use synthetic observations and intercepted network calls. They do not verify a successful deployed snapshot request, fix the Windows host's broker connection, or demonstrate market returns. The changes remain in draft PR #1 until approved and deployed. After deployment, require the expected boot commit and new process plus `market_view` receipts marked `internal_benchmark_proxy` with source timestamps/feed, and successful research receipts or the new scoped failure classifications. Queue completion alone is insufficient. Existing fresh relay reports may correctly suppress the fallback.
