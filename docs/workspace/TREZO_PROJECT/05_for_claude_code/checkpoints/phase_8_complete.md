# Phase 8 — Nova Trade Rules & Alpaca Paper Engine — COMPLETE

> Built by Nova, 2026-05-21.

Phase 8 implemented Mike's revised 13-section trading rulebook
(`TREZO_PROJECT/01_handoff_specs/TREZO_NOVA_BOT_TRADE_RULES.md`) and moved
stock execution onto Alpaca's paper-trading API. It was built in eight
parts. KINDRIP moved to Phase 9 and live brokerage to Phase 10 to make
room for it.

## What shipped

### 8a — Alpaca paper client + account-aware sizing
- `agents/app/brokers/alpaca.py` — reads the Alpaca paper account
  (equity, buying power, day-trade status) and positions.
- `agents/app/paper/sizing.py` — sizes every trade off *current account
  equity*, so the dollar range scales with the account. The Bot Tuning
  risk slider is authoritative; the document's 0.5-2% numbers are
  defaults the slider overrides. Buying power is the only hard cap.

### 8a.2 — Account posture & capital allocation
- `agents/app/paper/allocation.py` — the AI picks a posture from account
  size (growth under $25k, balanced to $100k, income above) and splits
  capital into per-market-type dollar budgets. Trade Execution caps each
  trade by the remaining budget for its market type.
- Migration `0015` + a posture selector and dollar-override boxes on the
  Bot Tuning page.

### 8b — Alpaca paper order execution
- Stock trades route to Alpaca as bracket orders (entry + stop +
  take-profit). Crypto stays on Trezo's internal paper engine.
- Migration `0014` adds `broker` + `broker_order_id` to paper_positions.

### 8c — Safety kill-switches
- `agents/app/paper/killswitch.py` — the Risk Manager halts all new
  signals on a daily -3% or weekly -6% realized drawdown, 3 losing
  trades in a row, or 3+ broker rejects in a session.
- Migration `0016` adds the kill-switch state columns. Day/week
  baselines are self-maintaining (the old daily-reset was never wired).

### 8d — Market regime + symbol-quality filters
- `agents/app/strategies/market_filter.py` — stock signals are gated on
  broad-market direction (SPY/QQQ vs session VWAP) and symbol liquidity
  (price over $5, average volume over a million shares).

### 8e — Revised scoring + day-trade rules
- An overextension filter rejects signals that have run too far from
  their mean. The Position Monitor gained day-trade management for
  intraday strategies — force-exit at 3:45 PM ET, a 90-minute max hold,
  and a 75-minute stagnation exit. The reward:risk floor rose to 1.5.

### 8f — Opening Range Breakout engine
- `agents/app/agents/orb_scanner.py` — the **14th agent**. Detects
  confirmed breakouts of the first 5-minute range during 9:35-11:30 AM
  ET and emits `strategy='orb'` signals through the normal pipeline.

### 8g — Performance logging + feedback loop
- `agents/app/paper/performance.py` — win rate, profit factor,
  expectancy, drawdown, per-strategy breakdown.
- The Strategy Discovery agent was activated (was a stub) — it emits an
  hourly performance report and a review-due alert every 25 trades.
- Alpaca fill reconciliation — when an Alpaca bracket closes a trade,
  the Position Monitor marks Trezo's tracking row closed.
- New web page: **Performance** (the scorecard, kill-switch state,
  per-strategy breakdown, recent trades).

## Decisions made (worth remembering)

1. **The Risk Manager is the one gate.** Every signal flows through it,
   so kill-switches, the market filter, overextension and scope are all
   enforced in one auditable place.
2. **Stocks on Alpaca, crypto internal.** Alpaca's brackets and shorting
   suit equities; crypto keeps the 24/7 internal engine.
3. **The risk slider is the boss.** It overrides the document's risk
   percentages; buying power is the only hard ceiling above it.
4. **Kill-switches and posture changes only ever reduce risk.**

## What the user needs to do

1. Apply migrations `0014`, `0015`, and `0016` in the Supabase SQL editor.
2. Confirm `ALPACA_API_KEY` + `ALPACA_SECRET_KEY` are in `agents/.env`
   (done 2026-05-21).
3. Restart the agents (`nuke-agent-cache.bat`) — the bootstrap line
   should read **`count=14`**.
4. Restart the web app. New things to see: the **Performance** page, and
   the **Capital allocation** section on Bot Tuning.

## Known limitations / deferred

- **ORB options credit spreads** (doc Section 7) — needs credit-spread
  and iron-condor modeling that does not exist yet.
- **Strategy-specific scoring models** (doc Section 4) — a deeper
  pattern-engine refactor.
- **Spread / halt / slippage / data-quality filters** — need a live
  bid/ask quote feed (candidate: Alpaca's market-data API) and real
  non-modeled fills.
- Still single-user; per-user runtime is the Phase 5b deferral.

## Next phase

- **Phase 9: KINDRIP** — the innermost ring, children's portfolios on
  the Future Index Accounts from the One Big Beautiful Bill.
- **Phase 10: live brokerage** — real-money execution.
