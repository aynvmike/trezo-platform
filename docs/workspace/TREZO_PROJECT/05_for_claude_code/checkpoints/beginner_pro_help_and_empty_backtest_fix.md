# Checkpoint — Beginner/Pro, smarter Help search, and the empty-backtest fix

Date: 2026-05-26

## 1. Site-wide Beginner / Pro setting
- web/src/app/globals.css — new rules: html[data-experience="pro"]
  .beginner-only{display:none} and the inverse for .pro-only.
- web/src/app/layout.tsx — head script also applies data-experience
  before paint (no flash), default beginner.
- web/src/components/dashboard/experience-toggle.tsx — segmented control
  in the dashboard header, persists to localStorage, fires a
  `trezo-experience` custom event for any listening client component.
- Tagged explanation copy: backtest page intro + disclaimer, patterns
  page intro, Help "Still stuck?" hint. Convention is set: any
  explanatory block can be hidden in Pro by adding the class.

## 2. Help search answers typed questions
- web/src/app/dashboard/help/_help-content.tsx — kept the FAQ
  live-filter; added an "Ask Trezo" button + Enter handler that POSTs
  to /api/help/chat (the existing Claude-backed route) and shows the
  answer in a card above the topics. The empty-state copy was rewritten
  to point at Ask Trezo instead of saying it's "coming next".

## 3. Empty-backtest diagnostic (urgent fix)
The watchlist run was coming back all zeros — at TCS 700, nothing
crossed threshold on Core Winners. Two changes:
- agents/app/backtest/engine.py:
  - BacktestResult now records peak_tcs / peak_tcs_index /
    peak_tcs_direction — the strongest read seen during the run, even
    if no trade fired.
  - compare_strategies adds a top-level peak_tcs + peak_strategy
    (across every strategy tested).
- web/src/app/dashboard/backtest/_backtest-runner.tsx:
  - Default Signal TCS lowered from 700 -> 650 (matches what worked in
    earlier testing where AMSC fired +109%).
  - EmptyRun now reads "No trades fired at TCS X. The strongest read
    was TCS Y (direction) — try a threshold below that."
  - Watchlist row's Win-rate cell now shows "peak NNN" when trades=0
    (with a tooltip), so the table itself tells you what to do.
  - Compare view's banner names the peak strategy when nothing crossed.

## Verified
- engine.py compiles + functional check: with TCS 2000 (no trades), it
  still returns peak_tcs > 0 and compare_strategies returns
  best_strategy=null with the across-strategy peak.
- _backtest-runner.tsx: real (string-stripped) balance 0/0/0,
  1263 lines.

## Reference material from Mike (acknowledged, not acted on)
- ChatGPT share link about the market
- wealthyeducation.com indicators article
- optimusfutures.com strategies article
- Annuity-Insights.PDF
Mike said: "I would not put it over the agents — I think of these as
resources." So treated as context, not new strategies to wire in.

## Still queued
- Dividend Wheel: cycle state (sold put / waiting / assigned / covered
  call) + dividend & FPSL income + beginner explainer.
- Future projections for every account, factoring taxes — own section.
