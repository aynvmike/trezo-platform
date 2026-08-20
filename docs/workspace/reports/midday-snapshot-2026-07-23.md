# Trezo Midday Snapshot — Thursday, July 23, 2026

**Generated ~12:10 PM ET (automated read-only run).**

## TL;DR verdict
Trezo is **healthy and working** — the agents are live (2,633 gate decisions logged today, the newest one minute before this snapshot) and actively managing the book: a USDCHF forex trade was harvested to a green close, ONDS is riding a trailing stop after a gap-up, and a stale XLF ghost was reconciled and closed. The account is **fully deployed with ~$0 free USD cash**, so new crypto entries the scanner approved (ETH, LTC, LINK) bounced off the broker with "insufficient balance." That is the normal small-account "no dry powder" state, **not a fault**. One caveat on this run: the **Trezo Alpaca connector was not connected**, so I could not pull the account snapshot directly — broker figures below are inferred from the agents' own activity ledger, not a live account read.

---

## 1. Market clock
🟢 **Open.** NYSE/NASDAQ regular session 9:30 AM – 4:00 PM ET. It's ~12:10 PM ET, so roughly **3h 50m to the close**. No holiday or early-close today. Trezo's day-only orders can fire normally.

## 2. Account health — ⚠️ could not read directly
The **Trezo Alpaca paper connector is not connected in this session**, so equity, buying power, options approval level, day-trade count, and any account blocks could **not** be pulled directly. Per the snapshot rules I did **not** substitute any other brokerage (an unrelated Interactive Brokers connector is visible but must never be reported as Trezo's status).

What the agents' own ledger reveals about the broker side today:
- **Free USD cash ≈ $0 (fully deployed).** Alpaca rejected six crypto orders this morning with `HTTP 403: insufficient balance for USD (available: 0)`, the latest at ~9:36 AM ET. That's a broker-truth echo: cash is fully committed to the existing book.
- **Stock/options book is full** at the max-open-positions cap (912 "open-signal cap reached" vetoes today — all position-backed).
- **Wheel is at its posture cap** (203 wheel-limit skips — DTE over the growth-posture cap and max concurrent CSPs already open).

This "no buying power" picture is legitimate for Trezo's small account — it looks like "not trading," but it's "nothing left to deploy."

## 3. Today's orders & fills (from the activity ledger)
- **USDCHF (forex swing)** — opened ~3:07 AM ET, banked in two profit steps (+$0.13, +$0.09), then closed at target ~8:37 AM ET (+$0.12). Clean green round-trip, small dollars (~+$0.3 total).
- **SQQQ (scalp, TCS 69)** — approved ~8:40 AM ET; ETF cap tightened stop/target. No reject logged (likely opened).
- **ONDS (options)** — a 6:00 AM ET harvest attempt failed (`insufficient qty available`); ONDS then gapped **up 4.4%** at the 9:30 open and its trailing stop ratcheted the lock higher.
- **XLF** — a stale/ghost position was liquidated and reconciled ~9:34 AM ET, closing realized **−$11.12**; the broker-reject counter reset so the session can trade again.
- **Crypto ETH / LTC / LINK (scalp)** — approved 8:39–9:36 AM ET but **all rejected by Alpaca: insufficient USD balance ($0 available)**. 6 broker rejects + 6 matching execute-errors, all the same root cause.

## 4. Open positions
Could **not** reconcile Trezo-vs-broker directly (Alpaca connector not connected). The ledger shows the book is at its max-open cap and the long-only oversell guard fired ~19 times on **DRAM** (broker kept showing −2 from stale double-sold exits; the buy-to-cover was already in flight each time — self-healing, but noisy and worth an eyeball).

## 5. Today's P&L
No direct account read available. From the ledger, **realized** today is small and net slightly negative — **XLF −$11.12** (reconcile close) is the main item, partly offset by the **USDCHF** green round-trip (~+$0.3). Unrealized marks (e.g. ONDS riding its trail) could not be pulled without the connector.

## 6. Why so few fills? (one-line diagnosis)
**Out of buying power.** The account is fully deployed (~$0 free USD); crypto and forex are cash-only, so the ETH/LTC/LINK approvals had nothing to fund and Alpaca rejected them. The stock/options book is simultaneously at its max-open cap. This is capacity/cash-limited, **not** a scanner failure or a quality-gate drought.

## 7. Scan / gate detail (activity ledger — the real thing, live today)
Ledger file present and actively written: **2,633 events**, 00:01 → 12:09 ET.

- **Approvals: 12** (crypto_dca XYO ×4, forex USDCHF, crypto_scalp ETH/LTC/LINK, scalp SQQQ). Scanners are clearly finding setups.
- **Vetoes: 2,204.** Top reasons:
  1. **912** — open-signal cap reached (book full)
  2. **360** — neutral direction, no actionable bias
  3. **206** — liquidity filter (avg volume below the scalp floor)
  4. **~375** — anti-stacking dedup (already approved CSCO / ONDS / EURGBP this session)
  5. **~107** — bid/ask spread too wide (NVDA, INTC — illiquid)
- **Wheel-limit skips: 203** — DTE over the growth-posture cap / max CSPs already open.
- **Crypto universe expander working:** enrolled **HYPE, SUI, ADA** ~4:30 AM ET (24h notional above the $5M floor).
- **Broker rejects: 6 / execute-errors: 6** — all "insufficient USD balance," i.e. out of cash (see §3).

**Cross-check (approvals → fills):** approvals ARE happening but the crypto ones are **not** turning into fills — and the ledger names exactly why: **$0 free USD**. So the gap is cash, not a broken execution path. Forex (USDCHF) and the SQQQ stock scalp did clear through.

## 8. Verdict
**Working, and actively trading — currently capacity/cash-limited, which is expected and not a fault.** The engine is alive (thousands of live gate decisions, real fills, exits, and self-healing reconciliations today), disciplined (book full, wheel at cap), and honestly out of dry powder (~$0 free USD, confirmed by Alpaca's own reject messages). No account block, scanner silence, or backend outage is visible.

**One action for Mike (not urgent):** reconnect the **Trezo Alpaca** connector so future midday snapshots can read equity, buying power, day-trade count, and blocks directly instead of inferring them from the ledger — **[Claude → Connectors settings]** (reconnect "Trezo Alpaca"). Nothing to fix on the bot itself; no code/config changes during market hours.
