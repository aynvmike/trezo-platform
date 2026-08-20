# Phase 7.5 — Strategy Library & Adaptive Scope — COMPLETE

> Built by Nova, 2026-05-21.

Mike asked for two things: a library of proven quant strategies so he is
not mentally tracking dozens of them, and a bot that watches breaking
news and market events and adjusts its own strategy scope. Three agents
that had been stubs since Phase 5 were always framed-in for exactly this
job — Phase 7.5 switches them on and adds the engine that ties it
together. Built before Phase 8 (KINDRIP) because it sharpens every
trading layer already in place.

## What shipped

### Strategy Library (`agents/app/strategies/library.py`)
- 15 proven strategies as structured `StrategyCard` records — trend,
  momentum, mean-reversion, breakout, income, event-driven, volatility,
  rotation and stat-arb. Each card carries its thesis, the signals it
  uses, the regimes it suits/avoids, risk profile, and which Trezo layer
  it maps to.
- A `REGIME_PLAYBOOK`: for each of six market regimes, which strategy
  families to favor, trade smaller, or pause.
- It is a *resource the agents read*, not a runnable strategy — exactly
  the "library through the agents" framing Mike asked for.

### Market regime classifier (`agents/app/strategies/regime.py`)
- Reads a broad-market proxy (SPY) and classifies it into one of:
  trending_up, trending_down, choppy, high_volatility, low_volatility,
  risk_off — from trend (price vs the 50-day average + its slope),
  volatility (annualized realized vol vs the window baseline), and
  drawdown off the recent peak.

### News + calendar (`agents/app/data/news.py`, `calendar_events.py`)
- `news.py` pulls Finnhub company-news and tags every headline with an
  event type (earnings, M&A, guidance, leadership, legal, analyst,
  product) and a sentiment score — a fast keyword pass, no LLM, so it
  runs cheaply every few minutes.
- `calendar_events.py` fetches the upcoming earnings calendar and
  ex-dividend dates (best-effort — the dividend endpoint may be premium).

### Two agents activated (were Phase 5 stubs)
- **Market Sentiment** — every 5 min, scans news for the equity
  watchlist and emits an `event` message for every material event.
- **Research** — every 10 min, sweeps the earnings/ex-dividend calendar
  and emits advance-warning `event` messages.

### Adaptive Scope engine — the 13th agent
- `strategies/adaptive.py` — pure decision logic: turns a regime read
  into a market posture, turns an event into a ticker flag. Hard
  guardrails: it may only ever *reduce* risk (tighten stops up to 50%,
  raise the confidence bar up to +150, pause or flag) — never loosen it.
- `runtime/scope.py` — the live scope state the Risk Manager reads.
- `agents/adaptive_scope.py` — the agent. `tick` reads the regime and
  sets the posture; `on_message` reacts to events and flags tickers.
- **The Risk Manager now enforces scope** on every signal — it is the
  single chokepoint, so one wiring covers all strategies. It vetoes
  paused strategies and flagged tickers, applies the regime's TCS bump,
  and tightens stops by the posture multiplier.

### Autonomy modes
- Three modes on the Bot Tuning page: **suggest** (recommend only),
  **guarded** (apply risk-reducing moves within guardrails — the
  default), **full** (also act on lower-severity events). This is the
  "guarded, with a switch to full auto" Mike asked for.

### Storage + UI
- Migration `0013_adaptive_scope.sql` — `autonomy_mode` column on
  `bot_settings`, and a `strategy_scope_adjustments` audit-log table.
- New **`/dashboard/strategy`** page (sidebar → Settings → Strategy
  Engine): the live posture, the regime playbook, the scope-adjustment
  log, the detected-events feed, and the full strategy library.

## Decisions made (worth remembering)

1. **The Risk Manager is the one enforcement point.** Every signal
   already flows through it, so consulting Adaptive Scope there covers
   every strategy at once — no need to wire each scanner.
2. **The engine can only reduce risk.** Tighten, raise the bar, pause,
   flag — never loosen. Even "full auto" cannot push past the hard caps.
   This is deliberate: an autonomous tuner should fail safe.
3. **Pausing a base strategy pauses its variants.** Pausing "crypto"
   pauses crypto_scalp/swing/dca via a prefix check — so a risk-off
   regime takes the whole volatile crypto layer offline cleanly.
4. **Events are not given their own table.** They already persist as
   `agent_messages` rows (kind = 'event'); the dashboard reads those.
5. **The web library is a display mirror.** `web/src/lib/strategy-library.ts`
   mirrors the Python module so the dashboard can show it; the Python
   module stays the source of truth the agents read.

## What the user needs to do

1. **Apply migration:** run `db/migrations/0013_adaptive_scope.sql` in
   the Supabase SQL editor.
2. **Restart agents:** run `nuke-agent-cache.bat`. The bootstrap line
   should now read **`count=13`** (added `adaptive_scope`).
3. **Restart web:** close the Web window, run `start-web.bat`, hard-refresh.
4. New things to try:
   - **Settings → Strategy Engine** — the live posture, regime playbook,
     adjustment log, event feed, and the strategy library.
   - **Settings → Bot Tuning** — the new Adaptive Scope autonomy choice
     (Suggest / Guarded / Full).

## Known limitations / open items

- Sentiment is a keyword pass, not an LLM read — fast and cheap, but it
  will miss nuance. An LLM upgrade is a candidate for Phase 5b (where
  NeMo Guardrails also lands).
- The regime proxy is SPY only; a multi-index read would be richer.
- "Suggest" mode records recommendations but the dashboard does not yet
  have an approve/apply button — approval UI is a follow-up.
- Ex-dividend calendar depends on a Finnhub endpoint that may be
  premium-gated; it degrades to empty if unavailable.
- Still global (single-user) settings — per-user runtime is Phase 5b.

## Next phase options

- **Phase 8: KINDRIP** — the innermost ring (children's portfolio), on
  the Future Index Accounts from the One Big Beautiful Bill.
- **Suggest-mode approval UI** — buttons on the Strategy Engine page.
- **Phase 5b: per-user runtime + NeMo Guardrails + LLM sentiment.**
- **Phase 9: live brokerage** — real quotes and execution.
