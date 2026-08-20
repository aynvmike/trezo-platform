# Phase 12 — feedback round (dark-mode fix, tax dropdowns, options Greeks)

Date: 2026-05-23
Status: COMPLETE

After testing the Phase 12 build, the user reported three issues plus a
question. The three fixes:

## 1. Dark-mode readability bug

In dark mode, native form inputs rendered bright white (the browser
default), and the pale emerald/red/amber -50 backgrounds (held cards,
win/loss banners, status chips) glowed near-white — text on them was
unreadable.

- globals.css gained an @layer base rule theming input/select/textarea
  backgrounds + placeholder to the theme variables (explicit bg-/text-
  utilities still override).
- emerald, red, amber are now CSS-variable-backed in tailwind.config.ts;
  light values = exact Tailwind defaults, dark ramp in globals.css .dark
  (50 = deep tint, 900 = light ink) — same approach as treasure/weave.
  So bg-emerald-50 becomes a deep green tint in dark mode and
  text-emerald-700 a light readable green. The "v1 limitation" noted in
  the 12b checkpoint is now closed.

## 2. Tax page — collapsible sections

Each tax-advantaged account is now its own Disclosure (collapsed); the
"Tax-saving strategies" list and the "age-based glide path" are each
wrapped in a single Disclosure. The personalised cards at the top
(employer match, withholding, child accounts) stay open. Much shorter.

## 3. Options Engine — the Greeks

- pricing.py — the Black-Scholes pricer now computes gamma, theta (per
  day), vega (per 1% IV) alongside delta; OptionQuote carries all four.
- options_strategies.py — every OptionsPlay carries net position Greeks
  (delta/gamma/theta/vega), summed sign-weighted across the legs and
  scaled to the whole trade; each leg dict also carries its Greeks.
- options_scanner.py — the options_idea payload now includes the Greeks
  (plus direction, expiration, contracts, modeled IV).
- The Options Engine page renders strategy ideas as cards with a
  four-chip Greeks row (delta / gamma / theta / vega) and a collapsible
  "How to read this" panel explaining each Greek in plain language.

## Verification

- All 79 agent files parse clean (ast sweep).
- All web files brace/paren/bracket-balanced.

## Open question (answered, not yet built)

The STMS watchlist is a fixed seed list today. The user asked whether it
should update from what the agent trades, from the portfolio, or from
what suits the market regime. Recommended a dynamic regime-aware +
portfolio-aware watchlist as a follow-up — awaiting his go-ahead.

## User-side steps

- No migration. Restart the agents service and the web app.
