# Backlog #119-122 — COMPLETE

Completed 2026-05-22. The four bigger backlog items from
DEFERRED_ITEMS_TRACKER.md, built in order.

## #119 — Multi-user foundation

- `runtime/settings.py`: `get_bot_settings(user_id=None)` — per-user
  lookup, cached per user. No argument = the global row (unchanged).
- `pattern_detection.py`: scans each user's own default watchlist and
  tags signals with that user's id; falls back to a shared founder
  watchlist when there is no per-user data.
- `risk_manager.py`: reads per-user settings when a signal is
  user-scoped, the global row otherwise. All backward-compatible.

## #120 — LLM sentiment + guardrails

- New `agents/app/llm/`: `client.py` (async Anthropic Messages call via
  httpx, Claude Haiku) and `guardrails.py` (input rail — caps and
  defangs injection attempts in untrusted news text; output rail —
  rejects any reply outside the permitted label set).
- `news.py` gains `assess_llm`; the Market Sentiment agent classifies
  headlines with the LLM under a per-tick budget, falling back to the
  keyword pass when the LLM is unavailable or a guardrail rejects it.
- Note: this is a lightweight, inspectable guardrails layer. Adopting
  the full NeMo Guardrails library (its Colang config + the dependency)
  remains a heavier follow-up; the rails here enforce the same intent.

## #121 — Backtest framework

- New `agents/app/backtest/engine.py`: replays historical candles
  through the same `calculate_score()` the live agents use, simulates
  long entries/exits, and reports win rate, profit factor, expectancy,
  total return and max drawdown.
- New `/backtest` endpoint on the agents service; `/api/backtest`
  proxy (auth-guarded); a `/dashboard/backtest` page with a runner UI;
  nav entry added.

## #122 — Options engine

- Credit spread (`build_bull_put_spread`) and iron condor
  (`build_iron_condor`) added to `options_strategies.py` and surfaced
  by the Options Scanner as ideas.
- Covered-call-after-assignment: when a Wheel cash-secured put settles
  as assigned, the scanner now sells a covered call above the assigned
  cost basis (`wheel_cc`), and settles it as called-away or retained.
- Closed options positions now feed the Tax Optimizer's estimate
  (stock + options); the wash-sale scan and price ledger stay
  stock-only.

## What the user needs to do

Restart the agents and the web app. No migration. Ensure the Anthropic
key is in `agents/.env` for #120's LLM path (it falls back gracefully).

## Verification

All agent files parse clean; web files brace/paren-balanced, no null
bytes. Backtest metric math and the strategy-weighting math were
spot-checked with synthetic data.
