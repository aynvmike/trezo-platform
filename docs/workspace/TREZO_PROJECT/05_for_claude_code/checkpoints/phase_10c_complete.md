# Phase 10c — Layer 4: Extended Strategy (the Swing Layer)

Date: 2026-05-23
Status: COMPLETE (10c.1 / 10c.2 / 10c.3)

## What this is

Layer 4 of the Woven Basket — the last unbuilt ring. Extended Strategy
is Trezo's MULTI-DAY SWING layer: the only layer that holds a position
across sessions. Every other ring is intraday (STMS, ORB, crypto scalp)
or premium-collection (Wheel, Dividends). Grounded in Section 5 of
TREZO_STRATEGY_RULES.md ("Layer 7 — Extended Stock Strategy"; the
protection-ring nav places it at Layer 4, between Options and the Wheel).

## 10c.1 — Strategy module + migration

- agents/app/strategies/extended.py — four swing-setup detectors, all on
  DAILY candles:
    * EMA50 pullback bounce  — uptrend pulls back to its rising 50-day
      EMA and bounces.
    * Breakout hold          — price broke a multi-week high and is
      holding above the breakout level (not a failed breakout).
    * Earnings-gap continuation — a recent 4%+ gap-up that has not
      filled and keeps progressing.
    * Stair stepper          — a steady ladder of higher highs / higher
      lows with shallow pullbacks.
  Plus: evaluate_extended() (runs all four, returns the best >= TCS 700,
  applies a +catalyst bonus), fomc_blackout() (Section 7C event gate —
  no new entries on an FOMC decision day before 2 PM ET), swing_window()
  (the scanner sweeps ~10 AM-3:30 PM ET), EXTENDED_WATCHLIST (12 liquid
  mid-caps, seeded from the founder's documented swing strengths),
  SWING_MAX_HOLD_DAYS = 7.
- Migration 0022_extended_strategy.sql — adds bot_settings.extended_enabled
  (boolean, default true).
- settings.py — BotSettings + _from_row gain extended_enabled.

## 10c.2 — Scanner agent + swing time-stop

- agents/app/agents/extended_scanner.py — the 17TH AGENT. Ticks every
  30 min, sweeps the watchlist during the swing window, runs the four
  detectors, emits one `signal` per stock per day tagged
  strategy='extended'. Sits out on an FOMC decision day until 2 PM ET.
- bootstrap.py — registers ExtendedScannerAgent (agent count 16 -> 17).
- Position Monitor — gained a multi-day time stop for strategy='extended':
  closes a swing position after ~5 trading days (7 calendar days). It
  does NOT apply the intraday 3:45 PM force-exit that STMS / ORB get —
  swing trades are deliberately held across sessions. Works on both the
  internal paper branch and the Alpaca branch.
- alpaca.py — added _delete() + liquidate_position() (DELETE
  /v2/positions/{sym}); the Position Monitor uses it to close an
  Alpaca-routed swing position past its window.
- trade_execution.py — Alpaca bracket orders for strategy='extended' now
  use time_in_force='gtc' so the protective stop/target legs survive
  past the session (a 'day' bracket would expire each afternoon).

## 10c.3 — Web + nav + Bot Tuning

- web/src/app/dashboard/extended/page.tsx — the Layer 4 page: scanner
  status, recent swing signals (ticker / setup / TCS / stop / target),
  open swing positions, closed swing trades, and a footer explaining the
  four setups and how positions exit.
- nav-config.ts — Layer 4 enabled (href /dashboard/extended; was
  disabled / phase-gated).
- Bot Tuning — a new "Extended Strategy — Swing layer" on/off toggle in
  the Strategies section, wired through _bot-form.tsx + _actions.ts.

## Verification

- ast.parse sweep: all 78 agent files compile clean.
- Functional test of extended.py: all four detectors fire on crafted
  daily series and a flat series yields None; evaluate_extended picks
  the best setup and applies the catalyst bonus; fomc_blackout and
  swing_window behave correctly (before/after 2 PM ET, weekday/weekend).
- All cross-referenced symbols confirmed to exist (fetch_company_news,
  fetch_candles_for, the extended.py exports).
- Web changes brace-balanced; the page mirrors the proven STMS page.
  (No node_modules in the build sandbox, so no tsc run — changes are
  minimal and mirror existing working components.)

## Deferred

- Supernova spike and Short-Squeeze penny-stock patterns — need an
  intraday feed to time safely (consistent with STMS's deferred
  intraday patterns).
- FOMC_DECISION_DAYS is a MODELED date list — keep it current against
  the Fed's published calendar. An empty/stale list simply means no Fed
  gate; it never forces a trade.

## User-side steps

- Apply migration 0022_extended_strategy.sql.
- Restart agents (count 16 -> 17, adds extended_scanner) and the web app.
- The Extended Strategy toggle is on by default in Bot Tuning.
