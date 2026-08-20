# Trezo Midday Snapshot — Tuesday, July 28, 2026 (~12:09 pm ET)

## ⚠️ Read this first: broker connector was NOT available this run
The Trezo **Alpaca** connector did not connect in this session (it needs
re-authorization). Per the rules of this report, I did **not** substitute any
other brokerage — the Interactive Brokers connector that *was* available is a
different, unrelated account and is never Trezo's status.

So the broker-side numbers — **equity, cash, buying power, options approval
level, day-trade count, account blocks, and the broker's own order list** —
could **not** be pulled today. Everything below comes from Trezo's own live
activity ledger, which is a reliable window into what the engine is doing, just
not into the broker's official balances.

**To restore full broker reporting:** [Cowork/claude.ai] re-authorize the
"Trezo Alpaca" connector in connector settings, then re-run this snapshot.

## 1. Market clock
Could not confirm via the Alpaca clock (connector down). Inferred **OPEN**:
it's a normal weekday and the engine filled live equity orders (WMT, INTC, CSCO)
during regular hours this morning — which only happens when the market is open.

## 2. Account health (broker side)
Unavailable this run — connector not authorized. No equity / cash / buying
power / options level / day-trade count / block flags could be read.
Note from the ledger: the **crypto USD wallet is collateral-locked and thin**
(~$447 available), which repeatedly blocked new crypto buys today (see §3).

## 3. Today's activity — from Trezo's engine ledger (authoritative when broker is down)
Ledger `logs/activity-2026-07-28.jsonl` is **live** (last write 12:09 pm ET),
**3,076 decisions** logged so far. The engine is clearly running and working.

**Orders the engine submitted today (8):** DOGE, WMT, INTC, ETH, CSCO, LINK,
and LTC (twice). Additional modeled fills: QNT, XYO, IOTA, XLM, USDCAD, USDCHF.

**Closes booked today (modeled P&L):**
- AUDUSD  +$1.20 (target)
- EURGBP  +$0.19 (target)
- LTC     +$0.06 (scalp net-edge)
- BTC     −$10.31 (manual/liquidation)
- XLM     −$12.10 (stop)
- ETH     −$38.72 (stop) ← the biggest loser; ETH stopped out, then re-entered
- **Net realized so far ≈ −$59.68** (small book; one ETH stop drove most of it)

**Rejects / errors (14 total, almost all one root cause):**
- **7 crypto rejects** on DOGE/LTC — all "HTTP 403 insufficient USD balance"
  (wanted ~$457, only ~$447 in the crypto wallet). This is the known
  crypto-collateral-lock squeeze, not a broken bot.
- **1 CSCO order** rejected locally: an inverted bracket (short take-profit sat
  *above* the stop). Worth a look — it self-corrected to a long later at 2:12 pm.
- Self-healing worked: "approval_slots_freed" cleared 1 leaked slot at 2:12 pm.

## 4. Open positions
Cannot reconcile against the broker this run (connector down). From ledger flow,
the book is **full at the 14-position cap** (see §5) — the engine is holding a
full slate across crypto, equities (WMT/INTC/CSCO), and forex.

## 5. Gate detail (deep) — 3,076 decisions
- **Approved: 30 · Vetoed: 2,646** (rest are housekeeping/scan events).
- Approvals by lane: crypto DCA 13, crypto scalp 8, extended 4, forex swing 2,
  crypto swing 2, default 1.
- **Top veto reasons:**
  1. **826 — "Open-signal cap reached (14)"** → the book is full; this is the
     dominant gate. Nothing wrong — it's the max-positions cap doing its job.
  2. 221 + 135 + 123 + 65 + 55 — **TCS below the 44 threshold** (scores 38–42),
     with crowding +9 because 10–14 names are already open in a correlated basket.
  3. 211 — **"Neutral direction — no actionable bias."**
  4. 92 — **"Already approved ETH this session"** (dedupe guard, working as intended).
- **Cross-check:** approvals ARE turning into orders (8 submits, several modeled
  fills), so the gate→fill path is intact on the engine side. The only fills that
  *didn't* clear were the crypto ones blocked by the USD-wallet shortage.

## 6. Why so few new orders
Single most likely reason: **the book is full (14/14 cap)** — 826 of today's
vetoes are "cap reached." Secondary: **crypto lane starved for USD collateral**
(the DOGE/LTC 403s). Neither is a fault — the engine is fully deployed and gating
correctly.

## 7. Verdict
**Working and actively trading (state b).** The engine is healthy: 3,076 live
gate decisions, 30 approvals, 8 orders submitted, closes and stops firing, and
self-healing cleaning up a leaked slot. Two things to watch, neither critical:
the **crypto USD wallet is too thin to take new crypto entries** (repeated 403s),
and one **CSCO inverted-bracket local reject** is worth a glance.

The **one gap in this report is tooling, not the bot**: the Alpaca connector
wasn't authorized this session, so broker-truth (equity, buying power, positions,
official fills) is unverified. Next action → [Cowork/claude.ai] re-authorize the
"Trezo Alpaca" connector, then re-run the snapshot for the full broker-side read.
