# Paper Trading + Live section · backtest chart · strategy carousel

Date: 2026-05-23
Status: COMPLETE (chunks 2 & 3 of the feedback batch)

## Chunk 2 — Paper Trading interactivity + a Live Trading section

- **Live Trading section** — new /dashboard/live page + a "Live Trading"
  nav entry under Paper Trading. It is the designated home for
  real-money trading: shows the current status (paper, live off),
  the ordered go-live steps, and a preview of what the page will show
  once live (live account, positions, P&L, venue & fills). Clean and
  honest — live stays gated until the go-live checklist is done.

- **Paper Trading quick actions** — a four-card action bar at the top
  of the Paper Trading page linking straight to Bot Tuning, Agents,
  Backtest and Watchlists, so the user reaches the key controls without
  hunting through the sidebar.

- **Backtest chart** — the web Backtest page already had a full
  BacktestChart component (a close-price line with green entry / win /
  red loss trade markers) but the engine never fed it. Fixed:
  agents/app/backtest/engine.py now returns `candles` ([{c}] close
  series) on every result, so the chart renders — the user can see the
  price action and exactly where each simulated trade opened and
  closed. (The backtest already persists to backtest_runs and feeds the
  agents' memory via Strategy Discovery — Phase 12d/13.)

## Chunk 3 — Strategy library flow

The Strategy library on /dashboard/strategy was already a horizontal
carousel — one swipeable strip per strategy family. The remaining
"long scroll" was the families stacked vertically, so the whole
Strategy library section is now collapsed into a Disclosure: the page
opens compact, the carousels are one tap away.

## Verification

- engine.py parses clean (ast); no `closes` refs left, `candles` field
  present.
- All edited web files brace/paren/bracket-balanced.

## User-side steps

- No migration. Restart the agents service (new backtest field) and the
  web app.
