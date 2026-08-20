# Trezo — Midday Snapshot · Thursday, 2026-07-30

Generated 14:08 ET (18:08 UTC). Read-only. No trades placed, no orders cancelled, no code or config touched.

---

## Headline

**The bot is awake and thinking, but nothing it decides is reaching the market.**
20 approvals today, **0 executions**, **18 order rejects**. Two specific, repeating faults are
blocking every single order. Both look like engine bugs, not market conditions.

---

## 1. Market clock

Regular session, Thursday 9:30am–4:00pm ET. No holiday. As of this report the market has
been open about 4h 40m with roughly 1h 50m left. Confirmed indirectly: the engine's stock lane
(PYPL, XLV) was actively scanning and firing inside regular hours.

## 2. Broker connector — NOT AVAILABLE THIS RUN

The **Trezo Alpaca connector did not load in this session** (the `trezo-alpaca:*` skills had no
underlying tools available). Per the standing rule, no other brokerage account was substituted —
the Interactive Brokers connector was deliberately **not** read, because it is a different,
unrelated account and must never be reported as Trezo's status.

That means these sections are **skipped, not zero**:

- Live equity / cash / buying power straight from Alpaca
- Options approval level and day-trade count
- Account or trading blocks
- Broker-side order list and position reconciliation

Everything below comes from Trezo's own activity ledger and the agents' daily digest, which are
independent of the connector. Where a broker number appears, it is the number the engine itself
recorded when it talked to Alpaca.

**Last known account read (agents' own digest, written 09:09 ET today):**

- Equity: **$4,800.45**
- Crypto-spendable USD: **$257.73**
- Open book: **13 positions** — 9 crypto, 4 stocks
- Concentration: ~5.73 truly independent bets; **69% of the book is one risk factor (crypto)**

## 3. Today's gate activity — the ledger IS working

`logs/activity-2026-07-30.jsonl` — 1,429 decisions, first 01:27 UTC, still writing at 18:08 UTC.

| Event | Count |
|---|---|
| veto | 947 |
| wheel_limit (CSP blocked) | 291 |
| scan_pool_refresh | 52 |
| **approve** | **20** |
| **broker_reject** | **18** |
| **execute_error** | **18** |
| closes (modeled fills) | 5 |

**Top veto reasons**

1. `Neutral direction - no actionable bias` — 129×
2. `TCS below threshold 44` with **crowding +9** — ~350× combined across score bands (35/36/42/43)
3. `Broker-only mode: Alpaca has no forex venue` — 50× (expected; forex is intentionally paused)
4. `Already approved X in this session - skip to avoid stacking` — ETH 47×, LINK 38×, WMT 33×

The crowding penalty (+9, from 8–9 open crypto names) is pushing borderline scores of 42–43 just
under the 44 floor. That is the risk system working as designed, not a fault — but it is the
single biggest reason good-ish setups aren't clearing today.

**Approvals: 20** — DOGE ×8, AVAX ×5, PYPL ×4, GRAB, XLV, LTC.
**Executions from those 20: zero.**

## 4. Why nothing executed — two concrete bugs

### Bug A — crypto orders sized a few dollars above the wallet (13 rejects)

Every crypto order came back `HTTP 403: insufficient balance for USD`. The pattern is identical
all day:

```
01:28  DOGE  requested 267.44  available 261.67   (short $5.77)
13:08  AVAX  requested 263.24  available 257.78   (short $5.46)
16:14  DOGE  requested 257.12  available 251.38   (short $5.74)
17:14  LTC   requested 257.32  available 251.54   (short $5.78)
```

The gap is **~$5.50–5.80 every time** — a constant, not random. The engine is sizing to the full
USD bucket without leaving room for the fee/spread buffer Alpaca reserves. It never wins this
race: the order is always about 2% too big. Every crypto approval today died here.

### Bug B — short brackets have take-profit and stop inverted (5 rejects)

```
14:08  XLV   short take-profit $163.33 must sit BELOW stop $163.01
15:09  PYPL  short take-profit $56.86  must sit BELOW stop $56.74
15:11  PYPL  short take-profit $56.90  must sit BELOW stop $56.77
16:14  PYPL  short take-profit $56.77  must sit BELOW stop $56.64
17:14  PYPL  short take-profit $57.27  must sit BELOW stop $57.14
```

On a **short**, profit is below entry and the stop is above. The engine is emitting them the long
way round — take-profit ~$0.13 *above* the stop every time. Trezo's own local bracket validator
caught it and refused to send, which is the guard doing its job, but it means **every short signal
today was thrown away**. PYPL cleared the gates at TCS 65–70 (the strongest scores of the day) and
still never made it to the broker.

### Also: the Wheel is capped out

291× `CSP skipped: 3 already open = the growth-posture max (1)`. Three cash-secured puts are
already open against a posture ceiling of 1, so the options lane is deliberately parked. Not a
fault — but worth knowing the wheel contributed nothing today by design.

## 5. Today's P&L (modeled book)

Five closes, all `fill_close_modeled` — these are positions the paper engine runs on live Kraken
data, **not** rows sitting at Alpaca.

| Time (UTC) | Symbol | Exit | P&L |
|---|---|---|---|
| 13:05 | IOTA | stop | **-$28.74** |
| 13:05 | IOTA | stop | **-$21.89** |
| 15:39 | XDC | stop | -$4.53 |
| 16:46 | XYO | target | +$4.39 |
| 17:17 | XYO | stop | $0.00 |
| | | **Realized** | **-$50.77** |

0 wins / 4 losses (one scratch). The two IOTA stops account for $50.63 of the $50.77 — one name
did essentially all the damage. Against the $48/day target (1% of equity) this is a red day, and
the $10/day floor was missed.

One partial: BITO banked 21 of 42 shares at step 1 but logged **"booking failed"**; the remainder
was re-protected with an OCO. Worth a look — the shares moved but the ledger entry didn't stick.

## 6. Verdict

**State (c) — working, but effectively broken at the last step.** The scanners, risk gates,
ledger and exit monitor are all alive and behaving correctly; the bot made 1,429 documented
decisions today and is still writing to the ledger right now. But **20 out of 20 approvals were
rejected at the broker**, for two mechanical reasons that will repeat every day until fixed:
crypto sizing is ~$5.75 above the available USD every single time, and short brackets have their
take-profit and stop the wrong way round.

This is **not** "no buying power" and **not** "nothing cleared the gates." Trades qualified. They
were built wrong and bounced.

**Next actions — both are code fixes, so NOT during market hours.** After the 4:00pm ET close:

1. `[Cowork chat]` Fix crypto order sizing to reserve the fee/spread buffer (leave ~2%, or size
   off `available - buffer` rather than the full USD bucket).
2. `[Cowork chat]` Fix short-side bracket construction so take-profit is placed **below** the stop.
3. `[PowerShell]` Re-check the connector: `Invoke-RestMethod http://localhost:8001/health` — this
   run could not reach the Alpaca connector or the backend from the sandbox, so equity, buying
   power and open positions here are last-known values from the agents' 09:09 digest, not a live
   broker read.

---
*Read-only report. Ledger: `logs/activity-2026-07-30.jsonl` (1,429 rows). Digest: `TREZO_DAILY_DIGEST.md`.*
