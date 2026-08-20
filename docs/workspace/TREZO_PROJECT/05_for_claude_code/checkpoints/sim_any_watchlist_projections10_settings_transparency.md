# Checkpoint — Four feedback fixes

Date: 2026-05-26

## 1. Simulation Lab — any watchlist + Promote
- /dashboard/simulation now lists every watchlist with a selector. The
  default selection is the user's "default" list but they can pick any
  custom watchlist they've created (testing list, thematic basket, etc.).
- New "Promote →" action in the By-ticker results table — adds a ticker
  to the default Core Winners list with one click. Already-on-Core
  rows show an "On Core" badge instead of a button.
- New /api/watchlists/promote route (POST {ticker}) — idempotent,
  uses lib/watchlists addItem; RLS-aware.
- /api/simulation/run accepts watchlist_id and resolves the chosen
  list server-side.

## 2. Future Projections — 10 account types
Expanded from 5 to 10: added Roth 401(k), SEP-IRA / Solo 401(k), HSA,
529 College Savings, and Series I Savings Bonds. Each has its own colour
in the chart, its own card with plain-English explanation, and the right
tax math (Roth-style for Roth 401(k)/HSA/529/Future Index; Traditional-
style for SEP-IRA; ordinary-income on gains for annuity/I-bonds).
I-bonds cap the modeled return at 4% to stay honest about realistic
yield.

## 3. Settings → Profile — Display preferences
New DisplayPreferences component on /dashboard/settings/profile reuses
the header ThemeToggle and ExperienceToggle so the theme + Beginner/Pro
switches live in Settings too, not only in the header chrome.

## 4. Pattern Engine — scoring transparency
The "How the score breaks down" Disclosure on /dashboard/patterns now
shows the outer TCS slices AND the inner 10-factor pattern score with
exact point values (8–12 each), plus a clear note: "every factor below
is worth between 8 and 12 points — close to even, no single factor can
dominate the score." Catalyst (+15) and the confluence bonus are
called out explicitly. A beginner-only sentence explains what a TCS
around 600 vs 700 means in plain words.

## Verified
All 6 touched / new files balanced. Stack-based brace check confirms
the patterns page is clean (the regex check false-positives on JSX
apostrophes, but the truth check is 0 unmatched).

## Still queued (Mike's earlier asks)
- Dividend / income-ETF library expansion (full YieldMax 50 + REX +
  iShares + Schwab + QQQ-family). Data-heavy but mechanical.
- Pattern Engine weight customization in Bot Tuning (let the user
  tilt the 10 factors).
- Alpaca Live wiring + go-live checklist (kept for last per Mike).
