# Trezo — Deferred Items Tracker

Every phase checkpoint carries a "Known limitations / deferred" note.
Read one at a time, those are easy to lose track of. This is the
rolled-up view: everything that was put off, in one place, with an
honest status. It is a living document — update it at the end of each
new phase.

_Recompiled 2026-05-23, after Phase 10c (Layer 4 — Extended Strategy).
All 7 Woven Basket layers are now built and enabled._

---

## Summary

The big news: the open list is now SHORT. Across the quick-wins batch,
the data-feed batch, the #119-122 backlog, the small-items sweep and the
dividend-DRIP work (all 2026-05-22), plus Phase 10c, almost everything
that was once deferred has been built. What remains genuinely open is
gated on things Trezo cannot manufacture itself — live brokerage fills
and paid data feeds.

- **Genuinely still open** — 4 items, all feed- or Phase-10-gated.
- **Resolved** — everything else. The detail below records what closed
  each item, so the history stays auditable.
- **By design** — 8 items that were never gaps, just deliberate choices.

---

## Genuinely still open

These cannot be closed with code alone — each waits on a data feed or on
live brokerage being switched on.

1. **Real-fill slippage modelling** (Phase 8) — Trezo's slippage/fill
   logic is modelled. True slippage handling needs real broker fills,
   which only arrive once Phase 10b live execution is on. Spread, halt
   and data-quality filters are already done.
2. **YieldMax real distribution feed** (Phase 2) — distributions are now
   MODELLED: the Dividend Manager agent credits a modelled weekly
   distribution per holding and DRIPs it. A real distribution data feed
   would replace the modelled figure with actual declared amounts.
3. **Full NeMo Guardrails library** (Phase 7.5 / #120) — the LLM
   sentiment path ships with a lightweight in-house input/output rails
   layer. Swapping in the full NeMo Guardrails library remains a
   follow-up (see the guardrails follow-up note).
4. **Phase 10b live brokerage activation** — the live executor is
   scaffolded (Phase 10b groundwork) but inert. Switching it on is
   gated on GO_LIVE_CHECKLIST.md and Mike's end-to-end paper testing.
   This is a planned phase, not an oversight.

### New deferrals from Phase 10c (Extended Strategy)

- **Supernova / Short-Squeeze penny-stock patterns** — the Extended
  Strategy swing layer ships four setups (EMA50 pullback, breakout hold,
  gap continuation, stair stepper). The two fast penny-stock patterns
  need an intraday feed to time safely — deferred, consistent with
  STMS's deferred intraday patterns.
- **FOMC date list is modelled** — `FOMC_DECISION_DAYS` in extended.py
  is a hand-maintained list of Fed decision days. Keep it current
  against the Fed's published calendar. An empty/stale list simply
  means no Fed gate; it never forces a trade.

---

## Resolved — and what closed each one

### Early corrections (closed by later phases)

- **Placeholder Supabase keys** (Phase 0) — real keys wired in Phase 1.
- **"Default strategy only"** (Phase 6a) — STMS, Crypto, Wheel, Options,
  ORB and now Extended were all built (Phases 6b-6e, 8f, 10c).
- **TCS act-on threshold 700 not 800** (Phase 4) — Bot Tuning default
  is 700.
- **Approximate intraday time stops / timezone** (Phases 6a, 6b) —
  Phase 8e added proper day-trade management with ET cut-offs.

### Quick wins — all 7 built 2026-05-22 (migration 0020)

Manual close-position button; KINDRIP $5k/yr cap hard-enforced;
withholding set-aside % saved as a preference; Suggest-mode approve/apply
buttons; live ETF valuation on the KINDRIP page; per-coin crypto loss
limits; footer legal links + drag-drop polish.

### Data-feed items — closed 2026-05-22 (+ verified 2026-05-23)

- **STMS float / catalyst / chart-pattern filters** — ALL THREE DONE.
  Float via `shares_outstanding_millions` (Finnhub), catalyst via
  `fetch_company_news`, the continuation setup via `stms_chart_setup`.
  Verified in the code 2026-05-23.
- **Live options pricing** — Options Scanner now prices Wheel CSPs from
  live Alpaca option quotes; Black-Scholes is the fallback.
- **Spread / halt / data-quality filters** — done (Alpaca market data).
  (Slippage still open — see above.)
- **Ex-dividend calendar** — wired into the Research agent.

### Bigger builds — all closed 2026-05-22 (verified 2026-05-23)

- **Multi-user / per-user runtime** (#119) — `get_bot_settings(user_id)`
  is per-user; Pattern Detection scans each user's own watchlist and
  tags signals; Risk Manager reads per-user settings. This also closes
  the old **"watchlist plumbing"** item — verified in pattern_detection.py.
- **LLM sentiment** (#120) — Market Sentiment uses Claude with a
  keyword fallback. (Full NeMo Guardrails still open — see above.)
- **Backtest framework** (#121) — `/dashboard/backtest` + the engine.
- **Strategy-specific scoring models** (#123) — per-family criterion
  weighting in the scorer.
- **More options strategies** (#122) — bull put spread + iron condor
  added (5 of the spec's 14); covered-call-after-assignment built.
- **Options trades into the Tax ledger** (#122) — done.
- **Quarterly child-portfolio reports** (#124) — on the KINDRIP page.

## By design (not gaps)

- Hand-rolled shadcn primitives (Phase 0) — deliberate, fewer moving
  parts.
- Finnhub returns $0 outside market hours (Phase 2) — upstream behavior.
- yfinance/Alpaca return the prior daily candle outside hours (Phase 4)
  — correct for pattern detection.
- No bus backpressure (Phase 5) — fine at current agent count.
- Self-employment tax not modelled (Phase 7) — trading gains are capital
  gains, so this is correct.
- Tax content is educational only (Phase 9.5) — a deliberate stance.
- Wash-sale scan is simplified (Phase 7) — same-ticker / 30-day.
- State 529 deductions described generally, not computed per state
  (Phase 9.5).

## Annual upkeep

- **Tax brackets and contribution limits** — centralised with a
  TAX_YEAR constant + an annual-refresh checklist in tax.ts, and a
  scheduled task (`trezo-annual-tax-refresh`, Jan 15) now runs the
  reminder. Still a yearly task, but automated and one-spot.

---

## How "deferred" stays visible

1. Every phase checkpoint keeps its own "Known limitations / deferred"
   section.
2. This tracker is the consolidated roll-up — update it at the end of
   each new phase: add new deferrals, move closed ones to Resolved.
3. Before declaring a phase done, its deferrals are listed here.
