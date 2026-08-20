# Trezo — Configure pages (design brief for Figma)

*Paste into the Figma chat to design the **Configure** sidebar section (collapsed by
default in the nav). Seven pages below. The 8th Configure item, **Setup Wizard**, is the
5-step animated onboarding already built at `/onboarding/tour` — see `TREZO_SITEMAP_AND_FLOW.md`.*

## Design language (Neo Obsidian — apply to all)

Dark-first: background `#0b0b11`, surface `#12121b`, foreground `#e6e3f2`, hairline borders
`#282838`, **gold accent `#c4964a`**. Fonts: DM Sans (UI), **Playfair Display** (H1/H2),
JetBrains Mono (numbers). Header pattern on every page: gold small-caps eyebrow → serif H1 →
one-line plain-English subtitle. Cards float on the obsidian with soft elevation (depth system).
Functional colors: emerald = safe/on, amber = caution, sky = info, rose = live/danger. Plain-English
sits beside every control ("here's what this does"). Configure is the "knobs" section — calm,
legible, never alarming; group dense pages into clear blocks.

---

## 1. Bot Tuning — `/dashboard/settings/bot`

**Purpose:** the dials that drive every agent — risk, confidence threshold, strategy on/off,
autonomy mode. Changes apply within ~30 seconds, no restart.

- **Header:** eyebrow "Settings — Bot Tuning" · H1 "How the bot behaves" · subtitle.
- **Bot Tuning form (the dials):** risk profile (Conservative / Balanced / Aggressive / Expert),
  a **confidence (TCS) threshold** slider, per-strategy **on/off toggles**, max open positions,
  **daily profit target + daily loss limit**, an **auto-trade** toggle (with a prominent ON/OFF
  banner), a strategy-switching mode (off / fixed / adaptive / tiered), and an **Expert mode**
  sub-section (per-stock pin / disable overrides). Include a live **sizing preview** (position size
  at your equity).
- **Settings Audit panel:** proves the saved values actually reach the agents at runtime (no hidden
  overrides) — a reassurance block.
- **Learning Insights:** a per-strategy stats table (win rate, avg win/loss, median TCS), an optional
  per-cycle breakdown, plain-English **tuning suggestions**, and a "your trade patterns" grid
  (held-too-long, exited-too-early, optimal…) from the post-mortem analyzer.
- **Trade Import:** paste a CSV or upload a statement (PDF / image / XLSX) to import trade history
  into the learning layer (two-step: upload → review extracted rows → import).
- **Design notes:** the densest control page — break into four blocks (Dials / Proof / Learning /
  Import). Sliders + toggles are the hero; expert section behind its own toggle; every dial gets a
  one-line "what this does."

## 2. Strategy Engine — `/dashboard/strategy`

**Purpose:** where the bot tells you which strategies it wants to favour, trim, or pause — and the
**Adaptive Scope** engine that reads market regime + breaking news and adjusts on its own (tightening
stops, raising the confidence bar, pausing a strategy, flagging a ticker).

- **Header:** eyebrow "Settings — Strategy Engine" · H1 "Strategy Engine & Adaptive Scope" · subtitle.
- **Strategy Proposals feed:** cards where the bot **proposes a change** (favour / trim / pause a
  strategy) with its plain-English reasoning; each card has **approve / dismiss** (resolve) actions.
  This is the bot "talking" to the operator.
- **Library + Adaptive Scope explainer:** what strategies exist and how the scope engine reasons over
  regime + news; collapsible detail, not a wall of text.
- **Design notes:** the proposal cards are the hero — conversational, calm, with reasoning and a clear
  accept/decline. Use a subtle "the bot is thinking" tone, never alarmist.

## 3. Ethical Filters — `/dashboard/settings/filters`

**Purpose:** what Trezo refuses to invest in. *"A treasure built on the backs of others isn't a
treasure."* Toggles control which categories are blocked when adding tickers; the always-on defaults
(human rights, OFAC, fraud) aren't shown because they can't be turned off.

- **Header:** eyebrow "Settings — Ethical Filters" · H1 "What Trezo refuses to invest in" · subtitle.
- **Filters form:** a clean list of category **toggles** (e.g. weapons, tobacco, fossil fuels,
  gambling, adult, predatory lending) with a one-line description each, plus a quiet note that the
  default screens are always on.
- **Design notes:** values-forward and calm; a tidy toggle list with plain-language descriptions; the
  gold/ethical framing carried in the copy and a small "always-on defaults" footnote.

## 4. Connections — `/dashboard/settings/connections`

**Purpose:** connect a broker — one-click OAuth sign-in across providers in three categories. Trezo
never sees your password or API key; you sign in on the broker's own page and they hand Trezo a
token, encrypted at rest.

- **Header:** eyebrow "Settings — Connections" · H1 "Connect a broker" · subtitle.
- **Provider grid:** broker **cards grouped into 3 categories**, each with a **Connect** (sign-in)
  button; connected providers show a connected state.
- **Broker Refresh Status:** a per-broker **health badge** (healthy / N failures / reconnect needed),
  last-refresh time + expiry, and a collapsible recent-attempts log.
- **Design notes:** provider cards with logos and unmistakable connected/disconnected states; keep the
  security reassurance ("you sign in on the broker's page — Trezo never holds your keys") prominent;
  health badges color-coded.

## 5. Live Trading — `/dashboard/settings/live`

**Purpose:** the paper→live switch. Live mode routes **real-money** orders through your brokerage.
Trezo is deliberately paper-only today (the live executor is the next phase); this is where it turns on.

- **Header:** eyebrow "Settings — Live Trading" · H1 "Live trading" · subtitle.
- **Mode state + switch:** an unmistakable **PAPER / LIVE** indicator and the (gated) go-live switch.
- **Go-live checklist:** the conditions before real orders can fire (live mode set, auto-trade on,
  broker connected with options approval / buying power) — a clear gated list.
- **Options Approval Badge:** your broker's live options approval level.
- **Design notes:** the highest-stakes screen — make the paper/live state impossible to misread; the
  switch should feel deliberate (a confirm step). Rose/amber for the live warning, emerald for the
  safe paper default.

## 6. Profile — `/dashboard/settings/profile`

**Purpose:** your account — capital, discipline rules, and tax filing status. Saved here, read by the
agents on their next tick (profit target / loss limit apply immediately).

- **Header:** eyebrow "Settings — Profile" · H1 "Your account" · subtitle.
- **Profile form:** capital (stock / crypto / options), **daily profit target + daily loss limit**,
  risk tolerance, and tax filing status plus the optional tax fields (income, employer match) that
  power the Tax Optimizer. Group into Capital / Discipline / Tax.
- **Display Preferences:** **theme** (light / dark) and an **experience level** toggle
  (Beginner / Pro) that controls how much explanatory copy shows across the app.
- **Design notes:** a clean grouped settings form; the experience toggle is a nice dimensional
  switch; "applies on next tick" reassurance.

## 7. Help & FAQ — `/dashboard/help`

**Purpose:** quick, plain-language answers — search or browse by topic, so the rest of the app stays
uncluttered.

- **Header:** eyebrow "Quick answers" · H1 "Help & FAQ" · subtitle.
- **Help content:** a **search box** + topic-grouped **Q&A accordions**.
- **Investment Vehicles:** an educational section explaining the instruments Trezo uses (annuities,
  futures, income / REX-style ETFs, options, crypto) in plain words.
- **Design notes:** search-first layout; accordions for Q&A; the education section as cards or
  accordions; calm and reference-like.

---

*Companion to `TREZO_PLAN_RESEARCH_DESIGN.md`, `TREZO_DESIGN_HANDOFF.md`, and
`TREZO_SITEMAP_AND_FLOW.md`. With this, the Figma set covers every sidebar section:
What's Happening, Wealth Layers, Plan & Research, and Configure.*
