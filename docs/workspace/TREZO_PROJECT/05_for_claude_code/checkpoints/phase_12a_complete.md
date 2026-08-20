# Phase 12a — Help system + less scrolling

Date: 2026-05-23
Status: COMPLETE

First part of the Phase 12 UX overhaul. Goal: cut how much a user has to
scroll and read on each page, and give them one reliable place to look
things up.

## Built

1. **Disclosure component** (components/ui/disclosure.tsx) — a reusable
   collapsible section on native <details>, no client JS. Dense
   secondary content collapses by default.

2. **Help & FAQ page** (/dashboard/help) — a searchable FAQ. ~20
   plain-language Q&As across 6 topics (Getting started, The seven
   layers, How trading works & staying safe, KINDRIP & family, Tax &
   budgeting, Account/data/settings). Server page + a client
   _help-content.tsx with a live search filter; matches expand as you
   type. This is the home for "how it works" detail so pages can stay
   lean.

3. **Help nudge** (components/dashboard/help-nudge.tsx) — a small
   dismissible pop-up, bottom-right, that points first-time users to the
   Help page. Appears ~1.8s after load; once dismissed it stays gone
   (localStorage). Wired into the dashboard layout.

4. **Nav** — "Help & FAQ" added to the core nav section.

5. **Less scrolling — applied** — the long explainer footers on the
   STMS and Extended Strategy pages are now collapsed into a Disclosure
   ("About this layer"), closed by default. The Disclosure is reusable
   for the other layer pages in later passes.

## Watchlists page reworked (addresses live user feedback)

The YieldMax block added in the polish sweep was too heavy — a full
always-open 17-card section. Reworked per the user's note:

- The YieldMax ETF universe is no longer its own section. It is now a
  uniform **box in the watchlist grid**, sitting alongside Core Winners.
- Every box carries a one-line description (Core Winners and the other
  watchlists included).
- The YieldMax box toggles its ETF library open in a panel below the
  grid — a tab-like reveal — so the page stays compact. Held ETFs are
  tagged; the panel links to the Dividends layer to manage holdings.
- New client component _watchlist-grid.tsx; page.tsx slimmed to feed it.

## Verification

- All new/edited web files brace/paren/bracket-balanced.
- New files mirror proven patterns (the budget data-guide <details>,
  the existing card styling). No node_modules in the build sandbox, so
  no tsc run.

## User-side steps

- No migration. Restart the web app.

## Still in Phase 12 (in sequence)

12b dark mode · 12c Pattern Engine visuals · 12d backtest upgrade ·
12e Budget Mirror audit · 12f agent chat. Plus a new Phase 13 queued —
agent shared & evolving memory (user request).
