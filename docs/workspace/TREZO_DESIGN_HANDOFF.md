# Trezo — Design Handoff Brief

*Use this as the starting direction for Claude Design, a Figma build, or a designer.
It describes what Trezo is, how it should feel, and the screens + components to design.*

---

## Implementation status — 2026-06-18 (BUILT, in code)

The Neo Obsidian design is now implemented in the live Next.js app, not just a brief:

- **Tokens (live):** background `#0b0b11`, surface `#12121b`, foreground `#e6e3f2`,
  border `#282838`, **gold/treasure accent `#c4964a`** (the `--accent`, gold in both
  light and dark). Functional accents: emerald / amber / sky / rose.
- **Fonts (confirmed + loaded):** DM Sans (UI), **Playfair Display** (serif headers),
  JetBrains Mono (numbers) — loaded via a `<head>` link.
- **Hero (landing):** the Woven Basket is a **3D atom** — seven tilted gold orbital
  shells, glossy electrons, and a pulsing treasure nucleus tumbling in space (CSS 3D).
- **Depth system (live, all pages):** floating cards with hover-lift (`.depth-card`),
  raised panels, gold-glow, recessed wells, an ambient page backdrop (`.depth-page` on
  the dashboard `<main>`), and a mouse-parallax tilt (`DepthTilt`) used as a landmark on
  the Overview hero.
- **Screens wired to REAL data:** Overview, Trading, Agents (redesigned + live Alpaca
  data); Capital Sleeves; the 7 layer pages; onboarding (a 5-step animated wizard at
  `/onboarding/tour` plus the profile flow). Full map: `TREZO_SITEMAP_AND_FLOW.md`.

The sections below remain the design north-star — treat them as refinement targets now.

## What Trezo is

Trezo is a multi-strategy automated trading platform — a "Woven Basket" of seven
wealth layers running from the most volatile (outer ring) to the most protected
(inner ring), each its own bot strategy. It's operated by its founder directly, so
the interface has to make a complex, multi-agent system feel calm, legible, and
trustworthy — clarity beats density every time.

## Who it's for, and the tone

An operator-owner (not a developer) running real strategies and real money. The UI's
job is to turn a noisy, technical trading engine into something a confident
non-engineer can read at a glance and trust. Plain-English explanations sit next to
every number and control.

## Visual direction — "Neo Obsidian"

- **Mood:** sleek near-black obsidian with old-world warmth; a sharp/smooth duality —
  precise, exact data against soft, calm surfaces. Avoid the flat, templated SaaS look.
- **Base:** near-black obsidian backgrounds, layered neutral grays, soft borders
  (think neutral-800), rounded-xl cards, gentle elevation, a subtle obsidian sheen.
- **Warm accent ("treasure"):** a brass/gold used sparingly for section headers and
  emphasis — the old-world note.
- **Functional accents (already in use):** Active sleeve = emerald, Quick-Options =
  amber, Holding = sky. Profit = emerald, loss = a restrained red, caution = amber.
- **Typography (confirmed + live):** DM Sans (UI + data), **Playfair Display** (serif
  headers — the old-world note), JetBrains Mono (numbers).

## Layout & information architecture

Left sidebar, four intent-based groups (section headers in small-caps + the treasure
accent), with numbered chips on the layer items and a 2px left-border active indicator:

- **What's Happening:** Overview · Trading · Agents
- **Wealth Layers (outer → inner, 1–7):** 1 Crypto · 2 Stock · 3 Options · 4 Stock
  Weekly · 5 Wheel · 6 Dividends · 7 KINDRIP
- **Plan & Research:** Strategy Lab · Watchlists · Grasping Wallet · Capital Sleeves · Tax Optimizer
- **Configure (collapsed by default):** Bot Tuning · Strategy Engine · Ethical Filters ·
  Connections · Live Trading · Profile · Help

## Core components (the design-system pieces)

- **KPI / stat tiles** — value, sublabel, optional live pill.
- **Capital-sleeve cards** — a used/free budget bar, the velocity rule, and layer chips
  (see the Capital Sleeves page).
- **Signal cards** — terse 8-line format: ticker, bias, trade type, strike & expiry,
  entry range, exit target & stop, confidence (1–10), 2–3 sentence reasoning.
- **Agent activity feed** rows; **layer cards** (numbered, status, idle reason).
- **Disclosure panels** — diagnostics/troubleshooting tucked away, not on screen by default.
- **Banners** — trading mode (PAPER / LIVE) and auto-trade (ON / OFF): informational,
  never nagging.
- Buttons, toggles, chips, and data tables (open positions, today's execution feed).

## Design principles (hard-won — please honor)

- **Reduce noise:** wrap troubleshooting copy in disclosures; no persistent amber
  banners that nag on every page load.
- **Plain-English beside the numbers:** every metric and control gets a "here's the reason."
- **Group long pages into visual blocks** rather than one endless scroll (e.g. Trading =
  KPI tiles / open positions / market context / agent activity / settings preview).
- **Calm over dense. Trust over flash.**

## Priority screens to design (in order)

1. **Trading** — break the current long scroll into the five blocks above.
2. **Capital Sleeves** — per-sleeve budget / used / free, the velocity rule, and the
   account-scaled capacity (already scaffolded at /dashboard/sleeves).
3. **Overview** — at-a-glance health: P&L, open risk, what the agents are doing.
4. **A reusable layer-page template** that applies to all seven layers.

## Tech & handoff notes

- **Stack:** Next.js 14 (App Router) + TypeScript + Tailwind CSS. Components live in
  `web/src/components/dashboard`, pages in `web/src/app/dashboard`.
- Designs should map to **Tailwind utility classes + reusable React components**, so the
  design tokens become the Tailwind theme.
- **Dark-first:** Neo Obsidian is the product, not a dark-mode toggle.

## How to use this handoff

- **Claude Design:** open claude.ai/design, point it at the Trezo repo (so it reads the
  real components), and paste this brief as the direction. Refine, then export the handoff
  bundle and bring it back here — I'll wire it into the frontend.
- **Figma:** use this as the brief to build the component library + screens. Share the
  file link and I can read it via the Figma API and implement it in code.
- **Or hand it straight to me** and I'll build the screens directly in the codebase.
