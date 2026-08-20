# Live Market-Data Feed — COMPLETE

Completed 2026-05-22. Built in three parts at Mike's request, to unblock
the data-dependent items from DEFERRED_ITEMS_TRACKER.md. Everything is
best-effort — with no keys or on any error, callers fall back to Trezo's
modeled data, so nothing breaks when the feed is unavailable.

## Part 1 — Alpaca live quote feed + spread/halt filters

- New `agents/app/brokers/alpaca_data.py` — Alpaca market-data client:
  `get_quote` / `get_quotes` (live bid/ask) and `get_latest_bar`. Uses
  the existing Alpaca keys and the free IEX feed.
- `market_filter.py` gains `spread_quality_check()` — a wide bid/ask
  spread (illiquid, high expected slippage) or a missing quote during
  the session (possible halt) vetoes the trade. The Phase 8d deferred
  spread/halt/data-quality filters are now live.
- Wired into the Risk Manager's stock branch, after the overextension
  check.

## Part 2 — Live options pricing

- `alpaca_data.py` gains `get_option_contracts` (real listed contracts
  via the trading API), `get_option_quote` (live mid premium), and
  `live_option_pick` (finds the real contract nearest a target strike
  and expiration).
- `wheel.py` gains `refine_csp_live()` — replaces a modeled cash-secured
  put's strike / expiration / premium with the nearest real, live-quoted
  contract. `WheelLeg` gains a `live` flag.
- The Options Scanner calls `refine_csp_live` on every Wheel CSP; the
  position note and the `modeled` flag reflect whether pricing was live.
- Black-Scholes (`options/pricing.py`) is now the documented fallback,
  not the only path.

## Part 3 — Fundamentals (STMS small-float filter)

- New `agents/app/data/fundamentals.py` — `shares_outstanding_millions()`
  via Finnhub `/stock/profile2`, cached for the process lifetime.
- STMS gains `FLOAT_MAX_MILLIONS = 20.0`; the scanner skips a candidate
  whose share count is known and over 20M. Unknown float (free-tier gap)
  does not block — the other filters still apply.
- The ex-dividend calendar was already wired (the Research agent calls
  `fetch_ex_dividends`); it needed nothing.

## What the user needs to do

1. Confirm `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` and `FINNHUB_API_KEY`
   are set in `agents/.env` (the feed degrades to modeled data without).
2. Restart the agents. No migration, no web change.

## Verification

- All agent files parse clean (ast sweep).
- Every new fetch is wrapped best-effort — a missing key, a gated
  endpoint, or an API error returns None and the modeled path stands.

## Still deferred (smaller follow-ups)

- STMS catalyst filter (needs news-event tagging per ticker) and
  chart-pattern filter (needs intraday pattern detection).
- YieldMax distribution tracking (needs a distribution feed).
- Real-fill slippage measurement (needs live, non-modeled fills).
