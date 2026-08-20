# Trezo — Midday Snapshot · Wednesday, 2026-08-05

_Read-only health report. Generated ~12:09 PM ET. No trades placed, no orders cancelled, no code or config touched._

---

## Verdict first

**Trezo is healthy and actively trading — but it is leaking trades.**

The engine is alive: it has logged **4,449 gate decisions today**, the last one at **12:08 PM ET** (one minute before this report ran). It has banked **+$23.63 realized on 13 closed trades, 9 winners / 4 losers, profit factor 3.5**. The $10/day floor is cleared.

That's state **(b) — working and actively trading**. Nothing is broken, nothing is blocked, nothing needs restarting.

But three separate defects stopped good signals from becoming orders today. They cost trades, and one of them briefly paused the bot. Details in "What went wrong" below. **None of them should be touched until after the 4:00 PM close.**

---

## ⚠️ One caveat about this report

**The Trezo Alpaca connector did not come up for this run.** The MCP server never finished connecting, so the usual live broker reads — account-health, today's orders, reconcile-positions, daily-P&L — could not be called.

I did **not** substitute any other brokerage. The IBKR connector is a different, unrelated account and was deliberately left alone.

Instead, every broker number below comes from **Trezo's own reading of Alpaca**, written by the agents themselves:

- `TREZO_DAILY_DIGEST.md` — written 12:07 PM ET today
- `logs/activity-2026-08-05.jsonl` — 4,449 events, last write 12:08 PM ET

That is the same account, read one step removed. Treat the numbers as accurate as of ~12:07 PM, not as a live tick.

---

## Market clock

🟢 **Open.** Wednesday, August 5 — a normal full session, 9:30 AM – 4:00 PM ET. No holiday, no early close. At the time of this run: **12:09 PM ET, roughly 3h 51m to the bell.**

(Source: system clock plus the fact that the agents were actively scanning and submitting intraday orders. Not confirmed against Alpaca's own clock endpoint — connector unavailable.)

---

## Account (engine-side, ~12:07 PM ET)

| | |
|---|---|
| Equity | **$4,903.44** |
| Crypto-spendable USD | **$119.25** |
| Open positions | **11** — 6 crypto, 5 stocks |
| Stocks pocket | **$1,957 deployed of $1,864 allowed — full** |
| Realized today | **+$23.63** on 13 closes (9W / 4L) |
| Profit factor | **3.5** |
| Today's 1% target | ~$49.03 · $10/day floor **cleared** |

Equity drifted between **$4,886 and $4,905** across the session — it never sagged, which tells you nothing catastrophic happened to the book.

**On buying power:** the stocks pocket is genuinely full ($1,957 against a $1,864 ceiling) and crypto has only $119 of dry powder left. Eighteen otherwise-good signals were skipped purely because there was no room. **That is not a fault — that is a small account being fully deployed.** It is the correct behaviour.

Options approval level, day-trade count, and account-block flags could not be read this run (connector down). Nothing in the ledger suggests any account block: orders were accepted and filled all morning.

---

## P&L by lane

- **Crypto** — 5 closed, 4 green, net **+$16.21** (won $18.48 / lost $2.28)
- **Stocks** — 8 closed, 5 green, net **+$7.42** (won $14.61 / lost $7.19)

Crypto did the heavy lifting and did it cleanly — four of five closes were winners and the one loser cost $2.28.

**Concentration flag from the agents:** 11 positions but only about **4.69 independent bets**, because **55% of the book is crypto**. Those six coins will move together. Worth knowing, not worth panicking about at this size.

---

## Orders today

**13 orders submitted** and filled, spread across four strategies:

| Time (ET) | Symbol | Strategy | Side |
|---|---|---|---|
| 08:48 | AVAX | crypto_scalp | long ~$737 |
| 09:15 | BTC | crypto_scalp | long ~$120 |
| 09:33 | LTC | crypto_scalp | long ~$734 |
| 09:33 | INTC | extended | long 1 @ $99.66 |
| 09:37 | F | extended | long 9 @ $14.38 |
| 09:44 | SMH | stms | long 1 @ $580.45 |
| 09:44 | XLK | extended | long 1 @ $188.26 |
| 10:40 | XRP | crypto_scalp | long ~$414 |
| 10:46 | WMT | stms | long 6 @ $113.03 |
| 10:46 | SMH | stms | long 1 @ $571.09 |
| 11:18 | DOT | crypto_swing | long ~$630 |
| 11:44 | INTC | extended | long 4 @ $100.54 |
| 11:45 | BAC | extended | long 3 @ $63.24 |

**10 exit liquidations** also went out — DOT, LTC, XRP, PYPL, XLY, BTC, LTC again, BITO, RBLX, WMT. Exits are firing normally.

**6 orders were rejected.** All six for the same reason — see defect #2.

---

## The gate ledger — what the scanners actually did

**4,449 decisions logged, 00:40 → 12:08 ET.**

- **56 approvals** ("cleared all gates")
- **3,166 vetoes**
- Approval rate: **~1.7%** — the gates are doing their job as a filter

**Approved names:** INTC ×10, SMH ×7, SOXS ×6, AMD ×4, AMZN ×3, XLK ×3, SNXX ×3, RBLX ×3, NVDA ×2, PYPL ×2, XLY ×2, plus AVAX, BTC, LTC, XRP, DOT, F, WMT, BAC, GDX.

**Approved by strategy:** extended 42, stms 9, crypto_scalp 4, crypto_swing 1.

### Why signals were turned down

| Count | Share | Reason, in plain English |
|---:|---:|---|
| 924 | 29.2% | Confidence score (TCS) below the day's floor of 41 |
| 703 | 22.2% | Liquidity filter — average volume under the minimum |
| 554 | 17.5% | Already holding that name this session (anti-stacking) |
| 388 | 12.3% | No clear direction — no actionable bias |
| 186 | 5.9% | No live bid/ask quote — possibly halted |
| 164 | 5.2% | Forex paused — Alpaca has no forex venue (broker-only mode) |
| 149 | 4.7% | Spread too wide / illiquid |
| 15 | 0.5% | Position or pocket cap reached |
| 5 | 0.2% | Kill-switch tripped |

Two things worth noting inside that TCS bucket. The threshold sat at **41 all day**, and it was carrying a **+6 crowding bump** because six positions were already open in the crypto basket. So a lot of the 924 near-misses were crypto signals scoring 35–40 against a floor that the book's own concentration had raised. That is the portfolio-risk logic working as designed — it made the bar higher precisely because the book was already crypto-heavy.

The **703 liquidity vetoes** are the second-biggest bucket and they're mostly the market-wide expanded pool hitting thinly traded names. Expected, not a problem.

---

## What went wrong — three leaks

These are the honest findings. **All three are "money left on the table," not "bot broken."**

### 1. Approvals that died at sizing — 17 occurrences (biggest leak)

Seventeen times today, a signal cleared every gate and then produced **zero shares**:

> `Sizing produced 0 shares. equity=$4,903, risk=4.00% ($196.12), stop=$5.17, entry=$219.91, notional_cap=$196`

The per-trade **notional cap** kept coming out far too small to buy even one share — it read **$4, $7, $43, $117, $196, $470** at various points against stocks priced $36 to $278. When the cap is $7 and RBLX is $36, nothing can be bought.

Names lost this way: **AMZN ×3, SMH ×3, RBLX ×3, XLK ×2, XLY ×2, NVDA ×2, PYPL, GDX, HL.** Some of those were the highest-scoring signals of the day.

This is the single biggest reason approvals didn't turn into fills.

### 2. Inverted bracket levels → 6 rejects → kill-switch pause

Six orders were rejected before they ever reached Alpaca:

> `Bracket rejected locally: short take-profit $100.51 must sit BELOW stop $100.31 (levels inverted)`

Hit **INTC, PYPL, SOXS, SMH (twice), PLTR**. On short setups the take-profit is being placed above the stop instead of below — the levels are backwards.

**This one cost live trading time.** Three of those rejects landed inside 60 minutes and tripped the session kill-switch at **9:49 AM ET**. Trading paused until the rejects aged out — the last kill-switch veto was at **10:34 AM ET**, so roughly **45 minutes of the morning session** were spent halted because of a levels bug, not a market condition. The most recent inverted-bracket reject was **12:08 PM ET (PLTR)**, so it is still happening.

### 3. Wheel harvest can't close — 5 failures

NOK and AGNC cash-secured puts were both flagged for harvest at **3:55 AM ET** — NOK at **~68% of max profit**, AGNC at **~81%**, both past the 60% rule. Every buy-to-close attempt since has failed:

> `harvest order failed: HTTP 403: insufficient qty available for order (requested: 1, available: 0)`

Five failures across the day (3:44 AM, 8:36 AM ×2, 11:42 AM). Alpaca reports zero available quantity on contracts Trezo believes it holds. That's **profit sitting unbanked**, and AGNC's own re-evaluation now reads *"RISK: thesis deteriorating"* — premium fell to 0.04 from an 0.08 entry. Both puts expire **2026-08-07**, so there are two days to sort it out.

### Also worth a look (lower priority)

- **10 profit-step bookings failed** on PYPL, XLY, XLV, F — shares were banked but the booking write failed. Twice the remainder was **"NOT re-protected — naked-guard enforcing"** (XLY, PYPL), meaning the guard correctly refused to leave a position naked.
- **47 profit-step aborts**: *"legs did not cancel — aborted untouched."* Safe failure mode (it backed off rather than double-trading), but it means the step-out ladder isn't completing.
- **Wheel is capped at 1 CSP** under the growth posture — 108 skips. That's deliberate: capital stays free for the growth lanes.
- **14 `library_unreadable` entries** — files in the knowledge drop-box the agents still can't read.

---

## What to do

**Nothing right now.** It is 12:09 PM ET and the market is open. No code or config changes during market hours.

**After 4:00 PM ET, in priority order:**

1. **The notional cap** — find why it computes $4–$196 on a $4,903 account and starves 4% risk sizing. This is costing the most trades.
2. **Short-side bracket levels** — the take-profit/stop inversion. Fixing this also stops the kill-switch from eating trading time.
3. **Wheel harvest 403** — reconcile what Trezo thinks it holds in NOK and AGNC against what Alpaca reports, before Friday's expiry.

**The Alpaca connector** needs to come back up before the next scheduled snapshot, or these reports will keep running blind on the broker side. Worth checking the plugin's connection state in [Cowork chat] at the next session.

---

## Agents' own proposals (unchanged, evidence-only)

The agents wrote 4 rule-change proposals from today's evidence: `strategy_strong:forex_swing`, `strategy_weak:crypto_dca`, `strategy_weak:crypto_scalp`, `near_miss:unknown`. They never self-apply — they sit in `TREZO_AGENT_PROPOSALS.md` for review.

---

_Sources: `C:\Trezo\TREZO_DAILY_DIGEST.md` (12:07 PM ET) and `C:\Trezo\trezo-platform\logs\activity-2026-08-05.jsonl` (4,449 events, last write 12:08 PM ET). Trezo Alpaca MCP connector unavailable this run; no other brokerage was read._
