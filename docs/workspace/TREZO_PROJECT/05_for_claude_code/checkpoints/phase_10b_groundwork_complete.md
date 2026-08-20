# Phase 10b Groundwork — Live-Executor Scaffolding (real money stays OFF)

Date: 2026-05-23
Status: COMPLETE (groundwork only — live execution remains unreachable)

## What this is

Phase 10b is the real-money brokerage wiring. This checkpoint covers only
the *groundwork*: the plumbing that lets Trezo address Alpaca's LIVE
endpoint **without** turning it on. Real money stays off. The single
deliberate flip that would activate it (`_LIVE_EXECUTOR_AVAILABLE` in
`runtime/trading_mode.py`) is still `False`, so every code path below
resolves to the paper venue.

## Changes

1. **agents/app/config.py** — added two settings:
   - `alpaca_live_api_key` (env `ALPACA_LIVE_API_KEY`)
   - `alpaca_live_secret_key` (env `ALPACA_LIVE_SECRET_KEY`)
   Separate from the existing paper keys on purpose — live and paper
   credentials never share a variable.

2. **agents/app/brokers/alpaca.py** — made the client mode-aware:
   - `LIVE_BASE_URL = "https://api.alpaca.markets"` constant added
     alongside the existing `PAPER_BASE_URL`.
   - `_live_active()` — returns True only when
     `trading_mode.live_trading_enabled()` is True. That function is
     hard-wired False in Phase 10a, so `_live_active()` is False today.
   - `broker_venue()` — returns `"live"` or `"paper"`; the public
     read-out of which venue calls currently hit.
   - `_base_url()` / `_headers()` — now branch on `_live_active()`:
     live URL + live keys only when the gate is open, paper URL + paper
     keys otherwise.

3. **agents/app/agents/trade_execution.py** — imports `broker_venue`
   and stamps `"venue": broker_venue()` into every Alpaca execute
   payload, so each recorded trade carries the venue it ran against.

4. **.env.example** — added `ALPACA_LIVE_API_KEY` / `ALPACA_LIVE_SECRET_KEY`
   placeholders (empty values only — no secrets).

## Safety verification

- All four touched agent files parse clean (`ast.parse` sweep).
- Gate sanity check: even with `TRADING_MODE=live` set,
  `live_trading_enabled()` returns False (because
  `_LIVE_EXECUTOR_AVAILABLE = False`), so `_live_active()` is False,
  `broker_venue()` returns `"paper"`, and `_base_url()`/`_headers()`
  resolve to the paper endpoint + paper keys. Nothing reaches the live
  API until the go-live flip.

## What is intentionally NOT done

- `_LIVE_EXECUTOR_AVAILABLE` is NOT flipped — that is the final
  go-live step, gated on `C:\Trezo\GO_LIVE_CHECKLIST.md` being fully
  worked through and on Mike completing end-to-end paper testing.
- No live order ever leaves Trezo in this state.

## User-side steps

- No migration for this checkpoint.
- Restart agents to load the new `config.py` fields.
- When the time comes to go live: fill `ALPACA_LIVE_API_KEY` /
  `ALPACA_LIVE_SECRET_KEY` in `agents/.env`, work through
  GO_LIVE_CHECKLIST.md, then flip `_LIVE_EXECUTOR_AVAILABLE` — that is
  the one and only switch.

## Verified alongside this work (task request)

Progress-section spot check confirmed done: tasks #12, #90, #99, #104.
