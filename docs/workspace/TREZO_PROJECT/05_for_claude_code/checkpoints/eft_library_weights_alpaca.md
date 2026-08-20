# Checkpoint — Income ETF library, Pattern weights tunable, Alpaca Live

Date: 2026-05-26

## 1. Income ETF library expansion
- web/src/lib/positions.ts — INCOME_ETF_LIBRARY now lists 54 ETFs across
  8 families: YieldMax (24), REX/NEOS/Roundhill (6), JPMorgan premium
  income (3), Global X covered call (4), iShares dividend (4),
  Schwab/Vanguard dividend growth (4), high-yield bond (4),
  REIT/MLP/preferred (5). Each entry carries a typical trailing
  distribution yield used as the default when added. YIELDMAX_LIBRARY
  is preserved as a filtered view for back-compat with the watchlists
  page.
- web/src/app/dashboard/yieldmax/page.tsx — re-rendered as a grouped
  library with a family heading + plain-English description, yield
  badge per card, "Held" indicator, and a custom-holding form that
  takes an optional yield input.

## 2. Pattern Engine weights tunable in Bot Tuning
- db/migrations/0025_pattern_weights.sql — new jsonb column on
  bot_settings; NULL = built-in fair weights.
- agents/app/patterns/scoring.py — DEFAULT_PATTERN_WEIGHTS (sum 100),
  _merged_weights(ctx), and the scoring loop reads `_w[factor]`. Every
  factor honours the override; clamped to 0–30.
- agents/app/runtime/settings.py — BotSettings.pattern_weights is read
  from the row.
- agents/app/agents/pattern_detection.py — passes per-user
  pattern_weights into MarketContext.
- web/src/app/dashboard/settings/bot/_bot-form.tsx — new "Pattern factor
  weights" section: 10 number inputs (Trend, Momentum, MACD, Volume,
  Breakout, Candle pattern, Bollinger, VWAP, Market alignment, IV
  environment) with default fallbacks.
- web/src/app/dashboard/settings/bot/_actions.ts — collects pw_* fields,
  clamps to 0–30, saves pattern_weights JSON only when the user
  tilted away from the defaults (otherwise NULL — agents read built-ins).

Verified live with a sandbox import: tilt trend to 25 → TCS rises and
breakdown.trend = 25 as expected.

## 3. Alpaca Live wiring + go-live checklist
- web/src/components/dashboard/live-banner.tsx — site-wide trading-mode
  banner. Green PAPER bar in paper mode; loud red LIVE bar when
  TRADING_MODE=live in the agents environment.
- web/src/app/dashboard/layout.tsx — banner sits above the header on
  every dashboard page.
- web/src/app/dashboard/settings/live/page.tsx — Settings → Live
  Trading. An 8-item checklist (live executor available, TRADING_MODE
  env, Alpaca live key + secret present, Risk Manager limits set, TCS
  threshold ≥ 700, 50+ closed paper trades, daily loss limit) with a
  green/amber summary, plus a plain-language explainer of how the two
  independent gates actually work.
- web/src/components/dashboard/nav-config.ts — "Live Trading" entry
  added to the Settings sidebar group.

## Safety
The live-execution gate stays exactly where it was — in
agents/app/runtime/trading_mode.py, `_LIVE_EXECUTOR_AVAILABLE = False`.
No remote flip. The web layer's job is visibility + the readiness
checklist. Flipping to real money still requires (1) setting the env
variable on the agents host and (2) shipping a Phase 10b release that
flips the constant after review.

## Verified
All web files balanced; agents compile and functional test passes.

## What's open
The Phase 10b live-executor itself — the real Alpaca live order
routing — is the multi-day build that follows. The platform is now
ready to receive it.
