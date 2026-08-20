# Trezo Midday Snapshot — Wednesday, July 8, 2026 (12:05 PM ET)

## Verdict
**The bot is healthy and working — but there is one bookkeeping discrepancy to fix tonight.** Scanners are alive (359 gate decisions this morning, 4 approvals), the SNDQ protective stop fired exactly as designed at the open, and the account has no blocks. New entries are idle for a legitimate reason: buying power is $0 because the 3 cash-secured puts pledge ~$4,600 of collateral against $4,710 equity — the account is fully deployed, not broken. The one real issue: **Trezo's books closed all 3 wheel CSP rows at 9:19 AM ET, but Alpaca still holds all 3 short puts.** The wheel agent is currently blind to positions it actually owns. No trading risk today ($0 options buying power blocks any new CSP), but it should be re-reconciled after the close. [Cowork chat] Ask Nova tonight: "re-import the 3 open CSPs into options_positions and find what closed them at 13:19 UTC."

## Market clock
🟢 Open (checked 12:04 PM ET). Normal session 9:30–4:00 ET; closes in ~4 hours. No holidays or early closes through Mon 7/13.

## Account health
| Field | Value | Status |
|---|---|---|
| Account status | ACTIVE | ✅ |
| Equity | $4,710.49 | — |
| Cash | $3,672.73 | — |
| Buying power | **$0** (RegT $0, options $0) | ⚠️ fully deployed, see below |
| Options level | 3 (spreads) | ✅ |
| Day trades (5d) | n/a (not reported on paper acct) | — |
| PDT flag | no | ✅ |
| Trading / account blocked | no / no | ✅ |

**Why $0 buying power is not a fault:** the three short puts (F $12.50, F $13, HPQ $20.50) require 100 shares' worth of cash each as collateral ≈ $4,600 — that's ~98% of equity. Until a put expires, is rolled, or is closed, there is essentially nothing free for new trades. This is the known "CSPs stay until roll-off" state from 7/6.

## Today's orders (1 total)
- **Filled:** SNDQ — SELL 265 shares, bracket stop leg. Stop was $3.41; SNDQ gapped through it at the open and the market order filled at **$3.2547** (9:36 AM ET). That's ~15¢ of gap slippage past the stop — normal behavior when a stock opens below your stop price, not a malfunction. This closed yesterday's 265 @ $3.57 buy for a realized loss of ≈ **-$84** at the broker (books recorded -$90.10 using a $3.23 mark — ~$6 mark-vs-fill gap, cosmetic).
- No rejected, canceled, or pending orders. No new entries (see buying power).

## Open positions — broker vs books
**Stocks (match ✅ 2/2):**
| Symbol | Qty | Avg cost | Now | Unrealized |
|---|---|---|---|---|
| CSCO | 10 | $114.07 | $112.84 | -$12.30 (+$10.50 today) |
| BITO | 1 | $8.64 | $8.36 | -$0.28 |

**Options (MISMATCH ⚠️ broker 3, books 0):**
| Contract (all short 1x) | Premium in | Now | Unrealized |
|---|---|---|---|
| F $12.50 put, exp 7/31 | $0.27 | $0.27 | $0 |
| F $13.00 put, exp 8/7 | $0.36 | $0.49 | -$13 |
| HPQ $20.50 put, exp 7/31 | $0.45 | $0.23 | +$22 (~49% of premium captured) |

All 3 CSPs sit open at Alpaca, but every matching options_positions row was flipped to closed_manual — once at 12:55 UTC (dupe cleanup, expected) and again at **13:19 UTC (9:19 AM ET)**, which orphaned the real positions. Until re-imported, the wheel agent won't manage rolls/exits on them.

## Today's P&L
- **Day P&L: -$56.19 (-1.2%)** — equity $4,710.49 vs yesterday's close $4,766.68.
- Realized: SNDQ stop-out ≈ -$84 (the whole story of the down day).
- Biggest movers since open: CSCO +$10.50, F 8/7 put -$8, F 7/31 put -$5.
- HPQ 20.5P has earned ~half its premium — a wheel-management candidate (another reason the books discrepancy matters).

## Scan / gate detail (activity ledger, 359 decisions)
- **4 approved / 355 vetoed.** Approvals: SOXS (extended, TCS 720) 9:21, RIVN (default, 670) 9:31, SOXS (scalp, 608) 9:34, RIVN (670) 9:34 — **none became orders**, consistent with $0 buying power sizing to zero. That is the correct behavior, not a silent failure.
- Top veto reasons: neutral direction / no actionable bias (192), "already approved PYPL this session — skip stacking" (48), same for BITO (23), ORB liquidity floors (~27), default liquidity floor (13).
- ⚠️ Small oddity: PYPL is blocked as "already approved" 48× but no PYPL position exists at broker or in books — a stuck session-state approval (it never became an order). Cosmetic today; clears on the next agent restart.

## Next actions (after 4 PM ET — no changes during market hours)
1. [Cowork chat] Have Nova re-reconcile options_positions (re-import the 3 live CSPs) and find what closed them at 13:19 UTC.
2. [Cowork chat] Mention the stuck PYPL session approval so it's cleared on the next restart.
