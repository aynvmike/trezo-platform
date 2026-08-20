# Trezo — Plan & Research pages (design brief for Figma)

*Paste this into the Figma chat to design the **Plan & Research** sidebar section.
It was missing from the main handoff. Five pages: Strategy Lab, Watchlists, Grasping
Wallet, Capital Sleeves, Tax Optimizer.*

## Design language (Neo Obsidian — apply to all five)

- **Dark-first.** Background `#0b0b11`, card/surface `#12121b`, foreground `#e6e3f2`,
  hairline borders `#282838`. **Gold accent `#c4964a`** for eyebrows, active states, emphasis.
- **Fonts:** DM Sans (UI), **Playfair Display** serif (page H1 + section H2), JetBrains
  Mono (all numbers, right-aligned/tabular).
- **Page header pattern (every page):** a gold small-caps eyebrow → serif H1 →
  one-line plain-English subtitle. A "beginner" expandable explainer can sit beneath.
- **Depth:** cards float on the obsidian (soft shadow + 1px top highlight), lift slightly
  on hover; pages sit on a faint lit-from-above ambient backdrop. Never flat.
- **Functional colors:** emerald = active/profit, amber = caution/options, sky = info/holding,
  rose = loss. Plain-English sits beside every number ("here's the reason").

---

## 1. Strategy Lab — `/dashboard/strategy-lab`

**Purpose:** one engine, three lenses — see what the bot sees right now, replay history, and
stress-test every strategy at once.

- **Header:** eyebrow "Strategy Lab" · H1 "Score, replay, stress-test" · subtitle naming the
  three lenses (Live Patterns / Backtest / Simulation).
- **Tab nav:** a segmented control with 3 tabs (gold underline/fill on the active tab).
- **Tab A — Live Patterns:** a responsive grid of **pattern cards**, one per watchlist ticker.
  Each card = ticker, a **TCS score 0–1000** as the hero number (mono, large), the detected
  candlestick pattern + timeframe, and a small price-action sparkline/snapshot. Below the grid,
  a collapsible "How the score breaks down": TCS = Technical/pattern 300 + Options environment
  250 + Fundamental/event 200 + Risk/reward 150 + Market 100; 700+ is the live-trade threshold.
- **Tab B — Backtest:** a runner **form** (watchlist or single ticker, strategy, TCS threshold,
  stop/target) → **results**: stat tiles (trades, win rate, profit factor, total return) + a
  trades table and/or equity curve.
- **Tab C — Simulation:** a harness **form** (watchlist, window 5/7/14/30 days, starting account
  size) → stitched-trade results across every strategy per stock, with a "**promote to Core
  Winners**" action on tickers that look good.
- **Design notes:** the TCS number is the star — use a 0–1000 confidence ramp. Pattern cards are
  the depth-card style; forms are compact and inline; charts render inside cards.

## 2. Watchlists — `/dashboard/watchlists`

**Purpose:** what the bot scans. Group tickers by theme; an income-ETF library feeds the Dividends layer.

- **Header:** eyebrow "Layer 2 — Watchlists" · H1 "Your watchlists" · subtitle. A "**New watchlist**"
  button sits top-right.
- **Global Add-Ticker bar:** a single ticker input plus a row of **list chips** (one per watchlist)
  to choose where the add lands; asset type (stock/crypto) is inferred from the list name. Ethical
  filters apply on every add.
- **Watchlist grid:** a **card per list** — name, item count, a "default" badge — that **inline-expands**
  (accordion) to reveal its tickers. Includes an **Income-ETF library picker** (cards from a curated
  library) that "pours into" the Dividends layer.
- **Design notes:** depth-cards with inline accordion expand; crypto vs stock chips color-differentiated;
  the income-ETF picker is a clearly separated sub-section.

## 3. Grasping Wallet — `/dashboard/budget`

**Purpose:** two motions of wealth — pinch the leaks today, then watch the freed dollars compound.
Private and in-browser (a statement is never uploaded).

- **Header:** eyebrow "Grasping Wallet" · H1 "Hold tight, then let it grow" · subtitle.
- **Section 1 · Today — "Where money goes":** a gold left-border section marker, then the **Budget
  Mirror** — a private in-browser spending analyser (import a statement → it categorises spend and
  simulates savings; nothing leaves the browser) + a short **Data Guide** on how to import.
- **Section 2 · Over the horizon — "Where every account is headed":** the **Projections Lab** — a
  long-horizon, after-tax projection across every account type, with "**what-if**" toggles
  (tax-loss-harvesting, donating appreciated shares) and sliders that update the projection in real time.
- **Design notes:** two clearly separated narrative sections, each with the gold left-border label;
  charts/projection curves are prominent; keep the privacy reassurance visible; sliders feel tactile.

## 4. Capital Sleeves — `/dashboard/sleeves`

**Purpose:** how capital is split by trade horizon, and how much of each sleeve is working right now.
*(This page is currently plain/unstyled — it most needs the Neo Obsidian + depth treatment.)*

- **Header:** H1 "Capital Sleeves" · subtitle. A summary strip: risk profile · account equity · "up to
  N positions" capacity, plus a one-line plan summary (e.g. "Active $2k / Options $1k / Holding $2k").
- **Three sleeve cards (side by side):**
  - **Active** (emerald accent) — intraday→next-day.
  - **Quick Options** (amber accent) — 2–3 day, take profit at +30% and recycle.
  - **Holding** (sky accent) — days→indefinite (wheel, dividends, crypto accumulation).
  Each card shows: **used $ / free $**, a **used-vs-budget progress bar**, budget $ + used %, the
  profit rule, the hold rule, and **layer chips** (which of the 7 layers feed that sleeve).
- **Design notes:** the budget bar is the hero; sleeve accent colors throughout; mono numbers; surface
  the **velocity** idea — fast-recycling capital takes a bigger per-trade bite than locked capital.

## 5. Tax Optimizer — `/dashboard/tax`

**Purpose:** a plain-English tax picture — what you'll owe, your quarterly payments, and which account
types shelter growth. (Estimates, not advice.)

- **Header:** eyebrow · H1 · subtitle (frame it as an estimate + "not your tax advisor").
- **Estimated tax breakdown:** stat tiles for the estimated liability (by bracket / federal + SE), with
  tone-colored values (mono).
- **Profile settings:** the filing-status + income inputs that drive the estimate.
- **Quarterly estimated payments:** a **table** (Quarter · Realized gain · Acquired · amount due).
- **Tax-advantaged accounts:** an educational, collapsible section explaining each account type in plain
  words (Roth / traditional / taxable, and the **Future Index Accounts** used by KINDRIP) — nested
  disclosures, not a wall of text.
- **Design notes:** numbers in mono; the breakdown tiles are the hero; account types as nested
  accordions; keep the disclaimer present and calm.

---

*Companion to `TREZO_DESIGN_HANDOFF.md` (the overall design language + the monitor/layer/onboarding
screens) and `TREZO_SITEMAP_AND_FLOW.md` (the full route map + flows).*
