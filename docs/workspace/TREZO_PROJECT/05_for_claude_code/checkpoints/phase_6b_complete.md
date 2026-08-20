# Phase 6b — STMS (Small Trades Momentum Strategy) — COMPLETE

> Built by Nova, 2026-05-20.

## What shipped

### Strategy module (`agents/app/strategies/stms.py`)
- `SEED_WATCHLIST` — 14 small-caps: the founder's STMS pool from
  TREZO_FOUNDER_WATCHLIST.md (STAFQ, NVIVQ, ZSANQ, XWEL, ZNB, JAGX, SDIG,
  GSAT, ACHR) plus 5 known morning-volatile names (SOUN, RIVN, PLTR, BB, AMC).
- `is_trading_window()` — STMS only trades 7-11 AM ET. Approximated as
  11:00-16:00 UTC, weekdays only. Proper `zoneinfo` handling deferred to 6c.
- `evaluate_candidate()` — computes price, daily-move %, and relative volume
  (vs 20-day average) for a ticker; returns a `StmsCandidate`.
- `all_filters_pass()` — true when price ($1-$20), daily move (+10%), and
  relative volume (5×) all pass.
- Thresholds as module constants: `TCS_THRESHOLD=750`, `PRICE_MIN/MAX`,
  `DAILY_MOVE_MIN_PCT=10`, `RELATIVE_VOLUME_MIN=5`.

### STMS Scanner Agent (`agents/app/agents/stms_scanner.py`)
- New agent — the **tenth** in the registry. Ticks every 90 seconds.
- Outside the 7-11 AM ET window: emits an idle heartbeat, scans nothing.
- Inside the window: for each watchlist ticker — fetch candles, evaluate
  the STMS filters, run `calculate_score`. If all filters pass AND
  direction isn't bearish AND TCS ≥ 750, emit a `signal` tagged
  `strategy="stms"`.
- Always emits a summary heartbeat (`tickers_scanned`, `candidates_found`).

### Strategy tag now flows through the whole chain
- **Risk Manager** reads `payload.strategy` and forwards it on the `approve`
  message.
- **Trade Execution** reads `strategy` from the message and passes it to
  `open_position()`, so the `paper_positions` row is tagged.
- **Position Monitor** already keyed its 11 AM ET time-stop off
  `strategy="stms"` — so STMS positions auto-close at end of window.
- Result: an STMS signal → STMS-tagged position → STMS time-stop. Full loop.

### Web UI (`web/src/app/dashboard/stms/page.tsx`)
- New Layer 2 page. Sidebar's "Stock Bot (STMS)" now points here (was
  pointing at the raw watchlist quotes view).
- **Scanner status banner** — green pulsing dot + "active" when inside the
  window, grey + "idle" otherwise. Shows last-scan stats.
- **Recent STMS signals** table — ticker, price, day move %, relative volume,
  TCS, timestamp. Sourced from `agent_messages` where `agent_name='stms_scanner'`.
- **Open STMS positions** — only `strategy='stms'` positions.
- **Recent STMS trades** — closed STMS positions with P&L and close reason.
- Footer documents the watchlist and which filters are live vs deferred.

## Decisions made (worth remembering)

1. **STMS is its own scanner agent**, separate from Pattern Detection.
   Different watchlist, different timing, different threshold (750 vs 700).
   Pattern Detection stays the general "candlestick patterns on the user's
   watchlist" scanner.
2. **Three of seven entry filters are live.** Price, daily-move, and
   relative-volume are computable from yfinance daily candles today. The
   other four are deferred:
   - **Float < 20M** — needs a fundamentals feed (Finnhub paid or similar)
   - **Catalyst (news event)** — needs news ingestion (Phase 5b)
   - **Bull Flag / Flat Top / Micro-Pullback** — these are *chart* patterns,
     not candlestick patterns; our 12-pattern library doesn't cover them.
     Needs a separate chart-pattern detector.
   This is honest scoping — the strategy works on what we can verify, and
   the deferred filters are documented in the UI so the user isn't misled.
3. **STMS uses the default 5%-stop / 10%-target** from the paper engine —
   which already matches the STMS spec exactly. No special sizing code needed.
4. **The 11 AM time-stop is approximate.** 15:00 UTC ≈ 11 AM ET in EDT.
   Phase 6c will do real timezone handling.
5. **Risk Manager still gates STMS signals** — TCS floor, open-position cap,
   and daily-loss-limit veto all apply. STMS doesn't bypass risk control.

## Exit criteria progress (Phase 6 overall)

| Criterion | Status |
|---|---|
| Paper bot runs for N consecutive days | ⏳ leave it running |
| Daily Profit Lock saves correctly | ✅ (Phase 6a) |
| Strategies execute without errors | 🟡 STMS live; Crypto/Wheel/Options still to come (6c-6e) |
| Performance dashboard shows realistic results | ✅ /dashboard/paper + /dashboard/stms |

## What the user needs to do

1. No new migration this phase — STMS uses existing tables.
2. **Restart agents** to load the new STMS scanner: double-click
   `nuke-agent-cache.bat`. Confirm the bootstrap line now reads **`count=10`**
   (was 9; +1 for `stms_scanner`).
3. **Restart web**: close the Web window, run `start-web.bat`.
4. Hard-refresh, then click **"Stock Bot (STMS)"** in the sidebar → lands on
   the new `/dashboard/stms` page.
5. The scanner only fires signals during 7-11 AM ET on weekdays. Outside
   that window it shows "idle" — that's correct, not a bug. To see it work,
   check the page on a weekday morning, or temporarily widen the window in
   `agents/app/strategies/stms.py` `is_trading_window()` for testing.

## Known limitations / open items

- Four of seven STMS filters deferred (see decision #2).
- STMS watchlist is hardcoded — Phase 6c can make it a user-editable watchlist.
- No manual position-close button yet.
- Timezone handling is approximate.

## Next phase options

- **Phase 6c: Crypto bot** — SCALP / SWING / DCA adaptive modes for XRP/ETH/SOL
  (24/7, no time window). Plus the Bot Tuning settings page with sliders.
- **Phase 6d: Dividend Wheel** — covered calls + cash-secured puts.
- **Phase 6e: Options strategies** — 3 of the 14 to start.
