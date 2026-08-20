# De-cluttered the remaining layer pages

Date: 2026-05-23
Status: COMPLETE

Rolled the collapsible Disclosure ("less scrolling") treatment across
the layer pages not reached in Phase 12a.

## Done

- **Crypto** — the "modes & how trades run" footer collapsed into a
  Disclosure; stale "Phase 9" copy fixed.
- **Dividend Wheel** — the watchlist / strikes / modeled-pricing footer
  collapsed; stale "Phase 9" copy fixed.
- **Performance** — the "how this scorecard updates" footer collapsed.
- **Strategy Engine** — the "how Adaptive Scope works" footer collapsed.
- **KINDRIP** — the large "Future Index Account" explainer box (near the
  top of the page) collapsed into a Disclosure, so the page opens
  straight to the children instead of a wall of text.
- **Dividends (yieldmax)** — checked: no dense prose explainer to
  collapse (the page is the tracker + ETF library + add-form, all
  functional). Left as-is.

Every layer/feature page that had a dense explainer block now keeps it
behind a collapsed Disclosure, consistent with STMS / Extended /
Patterns / Tax / Options from Phase 12a and the feedback round.

## Verification

- All five edited pages brace/paren-balanced.
- No node_modules in the sandbox — no tsc run.

## User-side steps

- No migration. Restart the web app.
