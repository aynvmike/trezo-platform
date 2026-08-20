# Pattern Engine — interactive detail, indicators, learner mode

Date: 2026-05-23
Status: COMPLETE

The user asked for: clicking a stock to see its detail, the pattern shown
with where it starts, hover explanations for learners, a beginner-to-
experienced detail setting, and the Pattern Engine watchlist named the
same as Core Winners.

## State — all five delivered

- **Clickable cards** — tapping a ticker card expands it to the full
  Trade Confidence Score breakdown: every score factor as a labelled
  row with its points.
- **Pattern location on the chart** — the MiniChart tints the last N
  candles (highlightLast prop) to mark roughly where the detected
  pattern formed.
- **Hover explanations** — pattern names and score factors carry plain-
  language tooltips from lib/pattern-glossary.ts (patternInfo /
  factorLabel / factorInfo).
- **Detail level** — a Learning / Standard / Pro toggle, remembered in
  localStorage. Learning shows full explanations on every pattern and
  factor; Pro strips down to just the ticker, score and chart.
- **Watchlist naming** — the page header now reads "your Core Winners
  watchlist — the same one you manage on the Watchlists page", so the
  correlation is obvious (no more vague "default watchlist").

## Verification

- lib/pattern-glossary.ts exports the three names the board imports;
  mini-chart.tsx has the highlightLast prop; all four Pattern Engine
  files brace-balanced; all 79 agent files parse clean.

## User-side steps

- No migration. Restart the web app.
