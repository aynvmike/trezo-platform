# Trezo Whole-History Trade Review — Stocks, then Options
**2026-08-20 · every closed and open position on the books, plus today's full veto record**

## The whole record at a glance

| Book | Lane | Trades | Wins/Closed | Realized | First | Last entry |
|---|---|---|---|---|---|---|
| 5k | stock | 235 | 109/231 (47%) | **−$107** | 05-26 | today |
| 5k | crypto | 101 | 54/98 (55%) | +$545 | 05-30 | today |
| 5k | forex | 19 | 12/19 | +$4 | 07-07 | — |
| 25k | stock | 38 | 23/38 (61%) | +$130 | 08-09 | **08-18*** |
| 25k | crypto | 65 | 43/61 (70%) | +$2,613 | 08-09 | today |
| 75k | stock | 45 | 27/44 (61%) | +$30 | 08-09 | **08-19*** |
| 75k | crypto | 68 | 49/65 (75%) | +$8,466 | 08-09 | today |
| all | options | 5 | 0 closed | $0 | 08-18 | 08-18 |

\* Those "recent" big-book stock entries are the reconciler adopting external fills, not the engine trading. Their last **scanner-driven** stock entries were both **08-14 at 17:02** — the same minute, on both books. Synchronized stops are configuration, not markets.

Crypto is carrying the platform: **+$11,624 realized** lifetime across books (75k's ladder alone +$8,466), win rates 55–75%. Stocks lifetime: **+$53 combined** on 318 trades. Forex: +$4 on 19 (its venue is gone now — signals auto-vetoed "Alpaca has no forex venue").

## Stocks — what the record actually says

**By strategy, lifetime:** the only stock strategy earning real money is `extended` (swing layer): 129 trades / +$109 on the 5k, +$50 combined on the big books before they went quiet. The losers: `pattern` −$116 (16 trades, July — before the friction work), `stms` −$41, `default` −$8, `scalp`/`orb` −$74 on 2 trades. The 5k's 47% stock win rate against 61% on the big books also says something: the big books only ever received the *survivors* of extended's global scan, while the 5k trades everything its own scanner surfaces. More filter = better trades.

**Why the big books stopped on 08-14, exactly:** the stock brain that still works — pattern_detection — walks *each user's default watchlist* and stamps its signals with that user's id. Only the 5k has a watchlist, and trade_execution treated the stamp as a fence: single-book execution, no fan-out. The extended scanner (global, market-first pool, still emitting 17–18 signals/day) has its survivors routed the same way. Result: everything funneled to the 5k; the big books' access ended the day that routing shape went live — and nothing alerted.

**The veto gauntlet (today's full count, ~4,800 vetoes):**

| Wall | Count | Note |
|---|---|---|
| Neutral direction — no actionable bias | 574 | signal quality, working as designed |
| **Open-signal cap reached (14)** | 516 | crypto occupies the slots; stocks starve behind it |
| Forex has no venue | 465 | by design until a forex broker exists |
| TCS below threshold (regime+3, crowding+6/7) | ~710 | scores 35–38 vs an effective bar of 44 |
| Volume floor (250k avg) | ~594 | kills mid-caps the scanners keep surfacing |
| **No price data for liquidity check** | 327 | data gap — appeared 08-19, zero on 08-18 |
| **No live bid/ask "possibly halted"** | 199 | IEX feed artifact — WMT is not halted |
| Spread too wide (e.g. RBLX "10.62%") | 166 | IEX top-of-book is sparse, not truly illiquid |
| Adaptive Scope material-event flags | ~200 | CSCO etc. |

Read that as three layers: **routing** (fixed tonight, below), **capacity** (slot cap + crowding — a settings/replay decision), and **data quality** (the IEX quote artifacts that began 08-19 — needs a look at what changed around the key/account work this week; a "quote unavailable" should not read as "halted" on a feed that's routinely empty).

## Options — short and specific

Five real short puts live at the venue, all adopted 08-18 12:04, all expiring **tomorrow (08-21)** except one 08-28: T $23p, BMY, AGNC ×3 across the three books. Tiny credits ($0.02–0.19), far out of the money — they'll most likely expire worthless tomorrow, which is the good outcome: premium kept, first realized options P&L on the books.

Beyond those five: the wheel scans daily on every book and fires — Alpaca blocks it at the last inch. The 5k's paper account **lacks options approval** (a dashboard toggle), and the 25k/75k attempts die on "no listed put contract near target" — the strike/DTE tolerance (`options_min_dte=7`) needs a replay against real chains before loosening. Nothing in the decision chain is broken.

## What changed tonight (commit 8bd442a — built, tested, NOT deployed)

Your rule, implemented: **access is the default; settings are the fence.**

1. **trade_execution** — a user_id on an approved signal is now *provenance* (kept as `origin_book`), never a fence. Every entry signal fans out to every book; each book answers with its own settings via the existing per-book gate (lane toggles, TCS floor, auto-trade). Payloads must explicitly say `book_scoped` to stay pinned (wheel legs, manual orders). A book added tomorrow starts receiving every strategy the moment it exists — nothing to remember, nothing to seed.
2. **pattern_detection** — when no book has a watchlist, it scans the *market pool* (same liquid-movers universe the extended scanner walks), not a hardcoded list. A watchlist now does what you said it should: narrow, by choice, in settings.
3. **Five guard tests** pin the routing rule so it can't silently regress again.

Not touched (replay first, your method): the 14-slot cap, TCS/crowding tuning, volume floors, the IEX quote artifacts, options approval/tolerance. Each is a one-decision item on the table with data behind it.
