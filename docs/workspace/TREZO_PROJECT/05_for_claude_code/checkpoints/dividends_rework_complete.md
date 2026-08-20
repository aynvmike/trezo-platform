# Dividends layer — tracks actual holdings — COMPLETE

Completed 2026-05-22, from testing feedback: the Dividends layer was
auto-seeding 5 placeholder YieldMax tickers, so a new user saw holdings
they did not own. It now tracks what the user actually holds.

## What changed

- **No more placeholder seeding.** `lib/positions.ts` no longer inserts
  5 default YieldMax positions. A new user's Dividends layer starts
  empty.
- **Add / edit / remove holdings.** New server actions in
  `yieldmax/_actions.ts`: `addHolding` (any ticker), `removeHolding`,
  and `saveHolding` (share count + DRIP toggle + estimated yield). The
  tracker card now has an editable share count and a Remove button.
- **YieldMax ETF library.** `YIELDMAX_LIBRARY` — 17 well-known YieldMax
  option-income ETFs (TSLY, NVDY, CONY, AMZY, the YMAX/YMAG/ULTY funds,
  and more). The Dividends page shows it as a pick list; one click adds
  an ETF to the user's holdings. ETFs already held show "In your
  portfolio."
- **Custom holdings.** A free-form add form — any dividend stock or
  ETF, not just YieldMax.
- The page header and the stale "Phase 7 / placeholder" copy were
  rewritten to describe the real, user-driven layer.

The dividend DRIP agent already operates on whatever `user_positions`
holds, so it now compounds the user's real holdings with no change.

## Note on placement

Mike asked for a YieldMax-ETF section "in the watchlist." It was built
on the Dividends page instead — that is where pulling an ETF into the
dividend portfolio actually functions. If a mirror in the stock
Watchlists page is wanted too, that is a small follow-up.

## What the user needs to do

Restart the web app. No migration (user_positions already has the
needed columns from migration 0021).

## Verification

All four touched files brace-balanced, no null bytes; no stale
references; the DRIP agent still reads user_positions correctly.
