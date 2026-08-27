# Trezo — Deferred Items Tracker

Every phase checkpoint carries a "Known limitations / deferred" note.
Read one at a time, those are easy to lose track of. This is the
rolled-up view: everything that was put off, in one place, with an
honest status. It is a living document — update it at the end of each
new phase.

_Recompiled 2026-08-27, after the 52-item audit of e08649d and its
same-morning clear-out (commit d1becae). This is now the canonical
deferred list; the clear-out artifact holds the item-by-item detail._

---

## Summary

The 8/27 audit found 52 items; 22 were fixed the same morning, and the
27 deferrals below each carry a written reason. The pattern the audit
named — **built but not bound** — is why this list exists: a deferral
recorded here is a decision; one discovered later is a defect.

- **Genuinely still open** — grouped by what unblocks each: Mike's
  decision, a feature build, a measurement, the web pass, or cleanup.
- **Resolved** — everything else, with what closed it (8/27 block
  added below; earlier history kept).
- **By design** — items that were never gaps, just deliberate choices.

---

## Genuinely still open (recompiled 2026-08-27)

### Waiting on Mike's decision — not code

1. **Kill-switch baseline is realized P&L only** — moving halts to a
   total-return baseline changes capital protection; owner's call.
2. **Acting on the variance-premium measurement** — it observes and
   reports mispricing; acting is a behavior change and belongs in a
   proposal (Mike's standing decision).
3. **Forex broker** — the Twelve Data adapter is built and the lane
   ticks dormant; it goes live when Mike settles the broker question.
4. **Phase 10b live brokerage activation** — scaffolded and inert
   behind GO_LIVE_CHECKLIST.md. A planned phase, not an oversight.

### Feature builds — real designs, not wiring fixes

5. **Assignment flow** (audit #30/#31) — detect assignment → create
   the stock lot → stand up the covered-call side; one design across
   two tables, the next engine feature after the report pipeline
   settles.
6. **U1/U2 unlock consumers** (#15) — laddering premium across
   expiries. U3's cap tightening already binds.
7. **`no_price_stop` consumer** (#16) — emitted, read by nothing;
   probably belongs to the watchdog.
8. **Lane rule 1 enforcement point, §5 readout, §6 projection
   surfacing** (#17 remainder) — the INCOME draw itself unlocked with
   migration 0058; these three still need designed homes.
9. **Held-name re-screen** (#27) — needs exit semantics (a fail on a
   held name is a decision, not a delete); the 7-day screen cache is
   the interim heartbeat.
10. **Covered calls priced live** (#33) — port the CSP path's
    live-quote refinement to the CC path.
11. **Advisor on the wheel's suggestion path** (#11 remainder) — the
    CC overlay is gated on both paths; wheel suggestions still bypass
    (they go to a human before money moves).

### Waiting on a measurement — no dial moves these gates

12. **Real-fill slippage** — needs live fills (Phase 10b); the 5 bps
    model + the live 75 bps breach halt stand in.
13. **UNPROVEN constants** (#23), including the wheel's 8.0%
    total-return assumption — the twelve-month verdict window decides.
14. **§7 measurement rails** (#22) — four for four unbuilt; need live
    history to measure.
15. **Two-ledger dividend reconciliation** (#21) — blocked on the
    mid-Sept first-pay-date probe (#20: endpoint works, 0 DIV rows on
    all three books as of 8/27).
16. **HRP covariance trustworthiness** — reported with a flag until
    enough joint history exists.

### The web pass — one coordinated pass, landed with CI

17. Mock-data fallbacks in the three redesign views (#44 — first, a
    live dashboard showing fake numbers is a lie with a UI) · trim
    dialog's dead endpoint (#38) · terse-format toggle no-op (#39) ·
    agent labels 8/30 + Wheel Bot mis-keyed (#40) · seven orphan
    components (#41) · unadopted page templates (#42) · run-now
    buttons 1/12 (#43) · views for four running lanes (#36) · **JS/TS
    tests + enforced lint** (#50), scheduled with the pass so it lands
    tested.

### Cleanup — safe only outside market mornings

18. **322 bare-`pass` exception handlers** (#5) — each needs judgment;
    the audit-named ones are fixed, the sweep is next-session work.
19. **41 dead symbols / ~734 dead lines** (#48) — deletion sweep.
20. **options_scanner extraction** (#28) — 2,853 lines; refactor risk
    with zero behavior gain, do it in a quiet week.
21. **KINDRIP real routing IDs** (#46) — needs data only Mike has;
    payloads stay marked placeholder.
22. **Full NeMo Guardrails** (#120, old list) — the lightweight
    in-house rails still stand in.
23. **Supernova / short-squeeze penny patterns + FOMC list upkeep**
    (Phase 10c carry-overs) — intraday feed still absent; the
    hand-maintained `FOMC_DECISION_DAYS` list still needs a calendar
    check now and then (stale = no gate, never a forced trade).

---

## Resolved — and what closed each one

### 2026-08-27 — the audit clear-out (d1becae) and the week before it

Twenty-two of the audit's 52 items closed in one pre-open commit; the
headline ones: relay failure alerts actually send (notify_sync);
detached-restart scheduling runs as SYSTEM with its outcome captured
and alerted; market briefs freed from the janitor gate (they had never
fired); watchdog covers 30/30 agents; web rebuild gated on a build
that compiled; per-name lane cap honored at execution; the wheel
advisor's collateral/earnings/tier checks all bound to real inputs,
with defer-or-SHRINK implemented end-to-end; reevaluator exempts
dividend/wheel/income rows (ex-div drops are the lane working, not
failing); Kraken's modeled fallback says so out loud; allocation
routes dividend_lt to the income pocket; the dead seed rotation
deleted; `_options_ideas` walks the rotating universe; four lying
comments corrected; migration 0058 added the migrations ledger +
`dividend_lane_mode` (applied 8/27 — INCOME/PARTIAL now reachable);
BACKUP-USB strips secrets, and 84e43cf added the one-click
RESTORE-FROM-USB with sanitized key templates.

Also closed this week, before the audit: the fund-vs-company screen
split (2c8c10d), repaired-cut readmission + split/specials/fragments
dividend data layer (eb271bb — this REPLACES the old "YieldMax real
distribution feed" open item: distributions now come from the broker's
corporate-actions feed with real ex-dates and amounts; payment
frequency still defaults quarterly where unknown, which understates
genuinely weekly funds), the forex data adapter (0f4fe5d), wheel bench
rotation (fbb1f61), the Market Desk report pipeline (b4ec566), and
boot-verified deploys (e08649d). PROJECT_STATUS.md recompiled 8/27 —
the audit's staleness finding (#52) is closed by that entry and this
one.

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
