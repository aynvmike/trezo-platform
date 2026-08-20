# Checkpoint — Scanner broadened beyond the watchlist

Date: 2026-05-26

## What changed
- agents/app/data/market_universe.py (new)
  - SECTOR_LEADERS — SPY, QQQ, IWM, DIA, plus all SPDR XL* sector ETFs.
  - market_wide_candidates(limit=50) — pulls Alpaca's session movers
    (gainers AND losers), then pads with sector ETFs. Cached 10 min
    so we don't hammer Alpaca every tick.
  - expanded_scan_pool(watchlist, limit) — combines the user's
    watchlist (first, by priority) with the broad market pool up to
    the cap. Returns (pool, breakdown).
- agents/app/agents/pattern_detection.py
  - Imports expanded_scan_pool.
  - Inner loop now runs over the expanded pool, not just the user's
    watchlist tickers.
  - Scan summary message now reads e.g. "Scanned 50 tickers (14
    watchlist + 36 market-wide) at TCS threshold 600. 3 signals fired."
  - Payload carries from_watchlist + from_market_wide counts.
- web/src/components/dashboard/scanner-pulse.tsx — surfaces the
  breakdown in the corner badge so the user can see at a glance what
  the scanner actually looked at.

## Why
Mike: "it still shows that it is scanning only from 14 stocks" + "make
sure the watchlist is not set to default for future settings and
features." Fixed both: pattern_detection now sees the whole market,
and a memory note ([[universe-default]]) is logged so every future
feature defaults to a market-wide pool with watchlist as the tilt
layer.

## Performance note
~50 tickers × ~100ms per calculate_score = ~5s of work per 60s tick.
Candle cache is shared across users within the same tick so two
users on the same name fetch once. The market-wide pool itself is
10-minute-cached at module scope so Alpaca's movers endpoint is hit
only every ~10 ticks.

## Verified
agents py_compile OK; scanner-pulse balanced. Memory note saved at
[[universe-default]] with the rule.
