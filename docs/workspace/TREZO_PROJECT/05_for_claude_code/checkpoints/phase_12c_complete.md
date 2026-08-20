# Phase 12c — Pattern Engine visuals

Date: 2026-05-23
Status: COMPLETE

Third part of the Phase 12 UX overhaul. The Pattern Engine page listed
scanned tickers as flat text rows. The user wanted the detected
strategies rendered more engagingly, with a chart snapshot showing what
the detector actually looked at.

## Built

- **agents/app/api/patterns.py** — the `/patterns/scan/{ticker}`
  response (ScanResponse) now includes a `candles` field: a compact
  last-40-bar OHLC snapshot. The scan already fetched the candles to
  score, so this is a near-free addition.

- **components/widgets/mini-chart.tsx** — MiniChart, a hand-drawn SVG
  candlestick snapshot. No charting library — light and sleek. Up
  candles green, down red; reads on both light and Neo Obsidian dark.
  Auto-scales to the high/low of the window.

- **_patterns-board.tsx** — rewritten from a flat list into a
  responsive **card grid**. Each card shows the ticker, direction,
  dominant pattern, TCS badge, the MiniChart snapshot, the detected
  pattern tags, and the confluence note. Loading cards show a pulsing
  chart skeleton; error cards a clear "No data". Still sorted by TCS,
  still scans sequentially to respect the data provider's free tier.

- **patterns/page.tsx** — the dense "How the score breaks down" footer
  is collapsed into the Disclosure component (consistent with 12a). A
  stale "the trade engine activates in Phase 6" line was corrected.

## Verification

- agents/app/api/patterns.py parses clean (ast).
- All web files brace/paren/bracket-balanced.
- No node_modules in the sandbox — no tsc/visual run.

## User-side steps

- No migration. Restart the agents service (new response field) and the
  web app.
