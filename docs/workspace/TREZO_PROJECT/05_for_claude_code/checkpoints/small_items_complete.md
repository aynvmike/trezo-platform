# Small-Items Sweep — COMPLETE

Completed 2026-05-22. Four lighter backlog items from
DEFERRED_ITEMS_TRACKER.md, built in one batch.

## #123 — Strategy-specific scoring models

`patterns/scoring.py` gained per-family weighting. The 10 scoring
criteria are re-weighted toward what a strategy family values:
breakout favours breakout/volume, mean-reversion favours
bands/VWAP, momentum favours momentum/volume, trend favours
trend/MACD. `calculate_score()` takes an optional `strategy`; the
STMS and Crypto scanners pass theirs. Unmapped strategies (and plain
pattern detection) keep the flat score, unchanged.

## #124 — Quarterly KINDRIP child-portfolio report

Each child on the KINDRIP page now has a "This quarter" panel —
the quarter label, dollars contributed so far this quarter, and the
account's current value, written in plain language.

## #126 — Annual tax-figures refresh

`lib/tax.ts` gained a `TAX_YEAR` constant and an "ANNUAL REFRESH"
checklist comment listing every dated table to update each year and
the IRS source. The Tax page now states which year's tables it uses.

## #130 — STMS catalyst + chart-pattern filters

- Catalyst: the STMS scanner now pulls recent company news
  (`fetch_company_news`); a recent news item sets the catalyst
  factor in the score.
- Chart pattern: `stms_chart_setup()` — a pole + shallow-pullback
  (bull-flag family) structural gate on daily candles. A precise
  intraday Bull Flag / Flat Top / Micro-Pullback detector would need
  an intraday feed and stays a deeper follow-up.

## What the user needs to do

Restart the agents and the web app. No migration.

## Still deferred

- YieldMax distribution tracking (needs a distribution feed).
- Real-fill slippage measurement (needs live, non-modeled fills —
  Phase 10).
- A precise intraday STMS chart-pattern detector.

## Verification

All agent files parse clean; web files brace-balanced, no null bytes.
Strategy weighting spot-checked (all criteria hit -> 100; momentum
factors score higher under the momentum family than flat).
