# Polish & Deferred-Items Sweep

Date: 2026-05-23
Status: COMPLETE

A housekeeping pass after Phase 10c — verify what is actually still
deferred, close the one real loose end, and make the tracker honest.

## 1. Verified the tracker's "still open" items

DEFERRED_ITEMS_TRACKER.md was compiled 2026-05-22 "after Phase 10a" and
had gone stale — several items it listed as open were completed later
that same day. Confirmed against the live code:

- STMS catalyst filter (#130) — DONE. stms_scanner.py fetches company
  news and feeds catalyst_today into the score.
- STMS chart-pattern gate (#130) — DONE. stms_chart_setup() is defined
  and gates the scanner.
- STMS small-float filter — DONE. shares_outstanding_millions().
- Watchlist plumbing (#119) — DONE. pattern_detection.py scans each
  user's own watchlist with a shared fallback.

So three "needs a feed" items and the "watchlist plumbing" bigger-build
item were already closed — the tracker simply had not been updated.

## 2. YieldMax ETF universe added to the Watchlists page

The flagged follow-up from the Dividends rework: the 17-ETF
YIELDMAX_LIBRARY lived only on the Dividends page. The Watchlists page
(/dashboard/watchlists) now has a "YieldMax ETF universe" reference
section — the full library, with the ones the user actually holds
tagged "Held", and a link through to the Dividends layer to add or
manage them. Read-only by design: the Dividends layer stays the one
functional home for adding holdings; the Watchlists page just surfaces
the universe. Wired via the existing positions.ts exports
(YIELDMAX_LIBRARY, getYieldMaxPositions) — no new data layer.

## 3. Corrected a stale docstring

agents/app/strategies/stms.py — all_filters_pass()'s docstring still
said "float, catalyst and chart-pattern checks are deferred." They are
not — they are applied in the STMS scanner (they need async data
fetches, which is why they sit there and not in this candle-only
helper). Docstring rewritten to say so accurately.

## 4. Recompiled DEFERRED_ITEMS_TRACKER.md

Rewritten to reflect reality after Phase 10c. The open list is now
short and honest — 4 genuinely-blocked items, each waiting on a data
feed or on live brokerage:

  1. Real-fill slippage modelling — needs Phase 10b live fills.
  2. YieldMax real distribution feed — distributions are modelled now;
     a real feed would replace the modelled weekly credit.
  3. Full NeMo Guardrails library — lightweight in-house rails ship
     today; the full library is a follow-up.
  4. Phase 10b live brokerage activation — gated on GO_LIVE_CHECKLIST.

Plus two new Phase 10c deferrals recorded: the Supernova /
Short-Squeeze intraday penny patterns, and the modelled FOMC date list.

Everything else moved to "Resolved", with a note of what closed it.

## Verification

- agents: stms.py parses clean (full 78-file ast sweep already clean
  from Phase 10c).
- web: the rewritten watchlists page is brace- and paren-balanced and
  reuses proven imports (cn, YIELDMAX_LIBRARY, getYieldMaxPositions).

## User-side steps

- No migration.
- Restart the web app to pick up the Watchlists page change.
