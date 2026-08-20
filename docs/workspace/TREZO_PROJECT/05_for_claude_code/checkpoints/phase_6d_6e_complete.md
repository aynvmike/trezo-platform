# Phase 6d / 6e — Dividend Wheel + Options Engine — COMPLETE

> Built by Nova, 2026-05-21.

Phases 6d (Dividend Wheel) and 6e (Options strategies) were built together
because they share one pricing core, one database table, and one agent. This
is the options layer of the Woven Basket — Layer 3 (Options Engine) and
Layer 5 (Dividend Wheel) both go live here.

## What shipped

### Black-Scholes pricing core (`agents/app/options/pricing.py`)
- `theoretical_price(option_type, spot, strike, dte, iv)` → an `OptionQuote`
  (premium, iv, the d1/d2 internals). The standard Black-Scholes-Merton model.
- `estimate_iv()` — derives an implied-vol estimate from recent daily-return
  volatility, since Trezo has no live options-chain feed.
- `daily_returns_from_closes()` — helper to feed the IV estimator.
- Risk-free rate fixed at 4.3% (`RISK_FREE_RATE`). Every premium in this phase
  is **modeled**, not a live market quote — this is stated on both new pages.

### DB migration 0012 (`db/migrations/0012_options_positions.sql`)
- New `options_positions` table: underlying, strategy, direction, option_type,
  strike, expiration, contracts, `net_premium_usd` (positive = credit received,
  negative = debit paid), `modeled_iv`, a `legs` jsonb for multi-leg spreads,
  status, `realized_pnl_usd`, and open/close timestamps.
- Status lifecycle: `open` → `closed_expired` | `closed_assigned` |
  `closed_manual` | `closed_profit`. CHECK-constrained.
- RLS: each user sees only their own rows. `updated_at` trigger attached.

### Dividend Wheel strategy (`agents/app/strategies/wheel.py`)
- The classic income cycle: sell a cash-secured put → if assigned, own 100
  shares → sell a covered call above cost basis → repeat.
- `evaluate_csp()` builds a cash-secured put ~5% below spot, ~30-day expiry.
- `evaluate_cc()` builds a covered call ~5% above spot, never below cost basis
  (so a covered call can't lock in a loss).
- Wheel watchlist: WMT, KO, JNJ, PG, CSCO, VZ, INTC — liquid, lower-beta
  dividend payers worth owning if a put assigns.

### Options strategy desk (`agents/app/strategies/options_strategies.py`)
- Three strategies to start (of 14 in the spec): `build_long_call`,
  `build_bull_call_spread`, `build_cash_secured_put`.
- Each returns an `OptionsPlay` with net premium, max loss, and max gain so
  the risk shape of every idea is explicit.

### Options Scanner Agent (`agents/app/agents/options_scanner.py`)
- The **12th** agent. Ticks every 30 minutes. Three jobs per tick:
  1. **Settle** — closes any modeled option past its expiration. A CSP that
     finishes out-of-the-money keeps the full credit; in-the-money, it's
     "assigned" and the loss is booked.
  2. **Wheel** — for every user with a paper account, opens a modeled
     cash-secured put on each Wheel name that has no open position.
  3. **Ideas** — emits Long Call / Bull Call Spread / CSP *suggestions* as
     `info` messages. These are surfaced only — never auto-executed.
- Registered in `bootstrap.py`; agent count is now **12**.

### Web UI
- **`/dashboard/wheel`** (Layer 5 — Dividend Wheel): four summary cards (open
  contracts, premium at work, cash secured, realized P&L), an open-positions
  table, a settled-positions table, and a plain-English explainer.
- **`/dashboard/options`** (Layer 3 — Options Engine): summary cards, a
  strategy-ideas feed from the scanner, the full options book, and a clear
  note that all pricing is modeled.
- Sidebar: Layer 3 "Options Engine" and Layer 5 "Dividend Wheel" are no longer
  greyed out — both are now live links.

## Decisions made (worth remembering)

1. **6d and 6e shipped as one unit.** They share `pricing.py`, the
   `options_positions` table, and `options_scanner.py`. Splitting them would
   have meant building the same plumbing twice.
2. **The Wheel acts; directional ideas only suggest.** Cash-secured puts are
   conservative (fully cash-collateralized, on names worth owning), so the
   scanner opens them automatically. Long calls and spreads carry real
   directional risk, so they are surfaced for review and never auto-traded.
3. **All pricing is modeled.** With no options-chain feed, premiums come from
   Black-Scholes. Both new pages say so plainly so the numbers are never
   mistaken for executable quotes. Live options data + execution is Phase 9.
4. **`net_premium_usd` sign convention:** positive = credit received,
   negative = debit paid. One column covers both income and directional legs.

## Repaired along the way

While compile-checking the agents, two files were found corrupted on disk —
`risk_manager.py` was truncated mid-line and `stms_scanner.py` had stray null
bytes (a Windows file-encoding glitch). Both were rewritten cleanly. All 12
agents now compile (`python -m compileall app` is clean).

## What the user needs to do

1. **Apply migration:** run `db/migrations/0012_options_positions.sql` in the
   Supabase SQL editor.
2. **Restart agents:** run `nuke-agent-cache.bat`. The bootstrap line should
   now read **`count=12`** (added `options_scanner`).
3. **Restart web:** close the Web window, run `start-web.bat`, hard-refresh.
4. New pages to try in the sidebar:
   - **Options Engine** (Layer 3) — strategy ideas + the full options book.
   - **Dividend Wheel** (Layer 5) — the cash-secured-put income cycle.
   The Options Scanner ticks every 30 minutes, so give it a cycle or two
   before positions and ideas populate.

## Known limitations / open items

- All option pricing is modeled (Black-Scholes), not live. Phase 9.
- 3 of 14 spec strategies implemented; the rest (credit spreads, iron
  condors, etc.) are future work.
- The covered-call leg of the Wheel exists in `wheel.py` (`evaluate_cc`) but
  the scanner doesn't yet write covered calls after assignment — the assigned
  shares need to land in the paper book first. Next refinement.
- Options positions are not yet fed into the Tax Optimizer's cost-basis
  ledger.
- Still global (single-user) settings — per-user runtime is Phase 5b.

## Next phase options

- **Phase 8: KINDRIP** — the innermost ring (children's portfolio), built on
  the Future Index Accounts from the One Big Beautiful Bill.
- **Phase 5b: per-user agent runtime** — makes settings, watchlists, and
  limits properly per-user; also where NeMo Guardrails goes on the LLM agents.
- **Wheel covered-call follow-through** — write CCs against assigned shares.
- **Phase 9: live brokerage** — real quotes and real execution.
