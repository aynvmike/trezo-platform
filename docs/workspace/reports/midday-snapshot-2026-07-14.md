# Trezo Midday Snapshot — Tuesday, July 14, 2026 (run ~2:16 PM ET)

**Verdict: Healthy and actively working.** The bot took profits and cycled positions all morning; it just isn't opening new stock/option entries because today's defensive market posture raised the quality bar (TCS floor 75) and nothing cleared it. That's the system doing its job, not a fault.

## Market clock
Open now. Closes 4:00 PM ET today; next open Wed 9:30 AM ET. Normal session, no holiday.

## Account health
| Field | Value | Status |
|---|---|---|
| Account status | ACTIVE | OK |
| Equity | $4,731.52 | — |
| Cash | $1,888.95 | — |
| Buying power | $8,399.86 (RegT $3,365.07) | OK — plenty of room |
| Options level | 3 (max at Alpaca) | OK |
| Day trades / PDT flag | not reported (PDT rule eliminated 6/4/26) | OK |
| Trading blocked / account blocked / suspended | no / no / no | OK |

Buying power is NOT the reason for quiet entries today — there's room to trade.

## Today's orders (7 total: 4 filled, 3 canceled)
**Filled**
- 4:47 AM ET — AVAX/USD sell 76.4 @ $6.508 (crypto exit, banked overnight scalp)
- 9:32 AM — SOXS sell 25 @ $4.09 (full exit)
- 9:35 AM — BAC sell 5 @ $60.24 and sell 5 @ $60.25 (profit-ladder trims, 10 of 11 shares banked)

**Canceled (all intentional)** — SOXS stop + first market attempt, and a BAC 6-share OCO leg: the "cancel protective legs first, then exit" dance working as designed. No rejects today.

## Open positions (8)
| Position | Qty | Entry → Now | Unrealized |
|---|---|---|---|
| ETHUSD (crypto swing) | 0.399 | $1,772.50 → $1,871.10 | +$39.37 (+5.6%) — stop ratcheted to breakeven |
| SPDN (inverse S&P hedge) | 82 | $8.63 → $8.63 | −$0.41 (flat) |
| PYPL | 14 | $47.79 → $47.17 | −$8.68 (−1.3%) |
| RBLX | 12 | $55.96 → $54.22 | −$20.88 (−3.1%) |
| BAC (remainder after trims) | 1 | $59.30 → $60.15 | +$0.85 |
| DOGEUSD | 284.2 | $0.0717 → $0.0746 | +$0.83 (+4.1%) |
| BITO | 1 | $8.64 → $8.75 | +$0.11 |
| F 7/31 $12.50 put (short CSP) | −1 | $0.27 → $0.13 | +$14.00 (52% of max — early-harvest fires at 60%) |

No Trezo-vs-broker discrepancies spotted; position set matches the strategies on the books.

## Today's P&L
Equity +$7.75 so far today (+0.16%), $4,723.76 → $4,731.52. Biggest movers today: ETH +4.7%, DOGE +4.0%, BITO +3.7% on the plus side; RBLX −1.5%, PYPL −1.0% dragging. Modeled forex/crypto lanes booked small closes: USDCHF +$1.12 (short hit target), AVAX +$2.67, USDCAD −$1.50 (stop), IOTA −$5.12 and XDC −$3.31 (setup-gone rotations).

## Why few new entries (gate detail — from today's activity ledger)
Ledger is live and busy: **4,140 logged decisions**, 3,823 vetoes, 1 new approval (USDCHF forex short — entered 4:47 AM, closed at target 12:30 UTC for +$1.12).
Top veto reasons:
1. 3,592× — TCS below the floor (defensive regime raised the bar +25 to 75; best candidates scored in the 60s)
2. 196× — neutral bias (no directional edge)
3. 32× — open-signal cap reached (10)
4. 3× — anti-stacking guard (PYPL/BAC/SOXS already held)
Plus 120 Wheel skips: available CSP expirations (~38 DTE) exceed the 21-day growth-posture cap — scanning fine, just no short-dated premium worth locking up.
Cross-check: the one approval was a modeled forex lane, so zero Alpaca entry orders today is consistent — approvals ARE turning into (modeled) fills; nothing is stuck.

## Watch items (no action needed now)
- BAC profit steps logged "booking failed" twice — the broker fills went through fine; reconcile's recovery pass should book the realized P&L. Check tomorrow's snapshot confirms it.
- After the second BAC trim the 1 remaining share was left without a fresh OCO ("naked-guard enforcing"). Enforcement exists for naked rows; worth one glance at tonight's log to confirm it re-armed.

*Read-only snapshot — no trades placed, no orders touched, no config changed. Broker data pulled directly from Trezo's Alpaca paper account (connector tools were unavailable this run, so the same account was read via its REST API).*
