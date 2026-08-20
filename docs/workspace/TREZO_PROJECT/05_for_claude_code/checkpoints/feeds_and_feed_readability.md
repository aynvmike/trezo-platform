# Data-feeds guide · dynamic STMS watchlist · readable activity feed

Date: 2026-05-23
Status: COMPLETE

Three things from the latest round of feedback.

## 1. Data-feeds setup guide

New plain-language guide at C:\Trezo\DATA_FEEDS_SETUP.md — for a
non-technical founder. Covers every feed Trezo uses: Supabase (database
+ auth), Alpaca (stock prices + paper trading + market movers),
CoinGecko (crypto, no key), Finnhub (news + fundamentals), Anthropic
(the AI), Upstash Redis (cache), and the yfinance fallback. For each:
what it powers, free vs paid, how to get the key, which .env file it
goes in. Plus how the three .env files work and a minimum-to-run list.

## 2. Dynamic STMS watchlist

The STMS watchlist was a fixed 14-ticker seed list. STMS is meant to
trade "stocks in motion", so it is now dynamic:

- agents/app/brokers/alpaca_data.py — new get_market_movers() hits
  Alpaca's stock movers/gainers screener (same Alpaca keys, no extra
  subscription).
- agents/app/strategies/stms.py — new dynamic_watchlist() pulls the
  session's top gainers, keeps the ones in the STMS price band
  ($1-$20), and falls back to SEED_WATCHLIST when the feed is empty.
- stms_scanner.py — the scanner now refreshes its hunting ground once a
  day from dynamic_watchlist() (cached per calendar day) and scans that
  instead of the fixed list; the scan-complete message reports whether
  the list is "dynamic" or "seed".
- The STMS page's "About this layer" note now explains the dynamic
  watchlist (and the now-stale "deferred filters" line was corrected —
  float / catalyst / chart filters are all live).

## 3. Activity feed — readable words, not raw JSON

The dashboard Activity box dumped each message's raw JSON payload. New
shared formatter web/src/lib/agent-message.ts — describeAgentMessage()
turns any agent message into one plain sentence (e.g. "Crypto scan
complete — 3 coins." / "Position check — watching 0 open position(s).").
Both the Activity feed (activity-feed.tsx) and the top ticker
(agent-ticker.tsx) now render through it, so neither shows raw JSON or
bare key names anymore. Agent and kind names are mapped to friendly
labels too.

## Verification

- All 79 agent files parse clean (ast sweep).
- All web files brace/paren/bracket-balanced.

## User-side steps

- No migration. Restart the agents service and the web app.
- Adding the data-feed keys: follow C:\Trezo\DATA_FEEDS_SETUP.md.
