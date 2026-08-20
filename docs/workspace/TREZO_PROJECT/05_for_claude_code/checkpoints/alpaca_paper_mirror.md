# Checkpoint — Alpaca paper account mirror

Date: 2026-05-26

## What changed
- agents/app/main.py — new GET /paper/alpaca-snapshot endpoint.
  Returns {configured, venue, account: {equity, last_equity, cash,
  buying_power, status, pattern_day_trader, daytrade_count,
  trading_blocked}, positions: [...], as_of}. Backed by the existing
  alpaca.get_account() + alpaca.get_positions() helpers.
- web/src/components/dashboard/alpaca-snapshot.tsx (new) — server
  component that fetches the snapshot, gracefully degrades. Three
  states:
    1. Alpaca NOT configured — small dashed card explaining how to
       wire it (set ALPACA_API_KEY + ALPACA_SECRET_KEY on the agents
       service).
    2. Alpaca configured but unreachable — amber error card.
    3. Alpaca OK — equity / today P&L / cash / buying power tiles,
       open-positions count, day-trade count + PDT flag, and a
       positions table with avg entry, mark, market value, and
       unrealized P&L (both $ and %).
- web/src/app/dashboard/paper/page.tsx — AlpacaSnapshot rendered
  above ScannerPulse, so the live broker truth is the FIRST thing on
  the Paper Trading page when configured.

## How the two ledgers coexist
- Alpaca is the authoritative source for cash, equity and positions
  when configured — exactly what Mike asked for.
- Trezo's internal paper_accounts row remains the ledger for the
  slower KPIs (vault, daily-lock progress, YTD/today realized P&L
  history). These show further down the page as before.
- They stay in sync because trade_execution still writes both: every
  Alpaca-routed fill records a row in paper_positions for our
  internal attribution / performance breakdowns.

## Verified
agents py_compile OK; web component + page balanced 0/0/0.
