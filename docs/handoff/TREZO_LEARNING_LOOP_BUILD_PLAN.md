# Trezo learning loop: implementation and next steps

Updated September 9, 2026. This document describes repository code and local synthetic tests. It does not report production account data or runtime audit results.

## Product goal

Build market-responsive agents that can create and evaluate strategy ideas within each account's risk policy. Desired income is a planning goal, not a fixed daily trading quota. Terminal visuals are optional; information quality, evaluation and execution correctness come first.

## Implemented in the review branch

- Restricted rule composition produces bounded historical strategy experiments and retains every attempted variant.
- Research uses explicitly scoped paper-account equity or configured fixed scenarios. Each experiment freezes its inputs; missing equity blocks dependent work.
- Discovery reviews seven completed UTC accounting days with complete pagination, immutable revisions and evidence-linked hypotheses.
- Market Desk can obtain a qualified SPY/QQQ benchmark proxy from existing market-data snapshots when fresh relay context is absent. Source timestamps and short expiry prevent old observations from becoming current merely through polling.
- Request-scoped, sanitized diagnostics distinguish account-read failures without reusing a historical or concurrent error.
- SQLite cleanup regressions and concise guard diagnostics support the Windows deployment gate.

These paths preserve existing risk limits. They do not place orders, transfer funds, establish verified profitability or automatically promote research candidates. The new observer and benchmark fallback require no LLM, Discord or Mem0 calls.

## Remaining connections

Trade-review hypotheses are not yet automatically replayed. A faithful adapter must match the actual strategy version, instrument, asset class, direction, timeframe and costs. A generic stock experiment cannot stand in for an options or intraday strategy replay.

Freeze the candidate plan before testing later data. Retain failed experiments and corrections, and separate exploratory historical replay from untouched later evaluation. Forward paper comparison and an explicit promotion controller remain necessary before a candidate can affect execution.

Verified performance also requires reconciled fills, fees, partial exits, account valuation and external cash flows. Recorded winning rows alone cannot establish a sustainable income amount. Forex needs dedicated currency and cost accounting plus a practice adapter before activation.

## Validation and deployment

Local checks passed: 73 guard suites with zero activity-log writes, and 1,099 pytest tests. Tests use synthetic data and intercepted network calls. They cover actual internal consumer bindings, account separation, source expiry, Windows timezone handling, incomplete reads and concurrent diagnostics.

Draft PR #1 remains subject to approval and deployment. Verify the deployed commit and actual consumer receipts separately; a green local suite is not a successful vendor connection or an account-return result. No new dependency or database migration is required by the current context/diagnostic additions.

See [agent information flow](TREZO_AGENT_INFORMATION_FLOW.md), [adaptive strategy specification](TREZO_ADAPTIVE_STRATEGY_SPEC.md), and [forex readiness](TREZO_FOREX_READINESS.md).
