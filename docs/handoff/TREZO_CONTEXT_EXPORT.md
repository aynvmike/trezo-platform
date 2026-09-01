# Trezo — Full Context Export

**Written 2026-09-01 for handoff to Claude Code.**
Purpose: carry everything learned across months of Cowork/Nova sessions into the repo, so
an agent starting cold can audit and extend Trezo without asking Mike for background.

Source of this document: the project-memory notes maintained across those sessions
(`trezo_environment`, `trezo_unfinished_audit`, `trezo_silent_failure_nets`,
`trezo_book_isolation`, `trezo_broker_truth`, `trezo_dividend_lane`,
`trezo_wheel_delta_gap`, `trezo_quantconnect`) plus a fresh inventory of the working copy
at `C:\Trezo\trezo-platform`, HEAD `d9512e1`.

Read `CLAUDE.md` at the repo root first — it holds the non-negotiable rules in short form.

---

## 1. What Trezo is, in one page

Trezo is a personal multi-agent trading platform. Three layers:

1. **The engine** (`agents/`, Python 3.12). A message bus plus a registry of 30 agents.
   Observers scan and propose; the Risk Manager approves or vetoes; actors execute. Agents
   tick on their own intervals through a scheduler, and also react to bus messages.
2. **The dashboard** (`web/`, Next.js 14 App Router + Tailwind + Supabase auth). ~40 pages
   under `/dashboard`, ~50 route handlers under `/api`. This is the "trading site".
3. **The API gateway** (`api/`, Express + TypeScript). Small: health, auth, profile. Most
   server work happens in the Next.js route handlers and the engine, not here.

Persistence is Supabase (Postgres + RLS), 58 applied migrations. Brokerage is Alpaca paper
across three accounts. Market data: Alpaca (equities, options chains, crypto), Finnhub
(fundamentals/metrics), Kraken (FX OHLC), CoinGecko, Alpha Vantage (being retired).

**Trading mode is paper.** `TRADING_MODE=live` exists as a switch but the live executor
was never built. Nothing about live money is wired.

### The three books

`agents/app/brokers/accounts.py` defines `_SLOTS = {"primary": "", "acct2": "_2",
"acct3": "_3"}` — three Alpaca paper accounts, keyed by env-var suffix. `bind_for_user`
binds a book before any broker call; `route_guard` refuses to act on an unresolved book.
All three are live and filling. One is a sub-$5k book, one is referred to as the "75k"
book. They must never interfere with each other (see §4).

---

## 2. The agent roster (30 registered)

Registered in `agents/app/runtime/bootstrap.py` ~lines 84–113. Tick intervals are class
attributes on each agent. `tick_interval_seconds = 0` means event-driven only.

| Agent | Role | Tick | What it does |
|---|---|---|---|
| pattern_detection | observer | 180s | Candlestick patterns, trade-confidence score 0–1000 |
| stms_scanner | observer | 180s | Small-cap momentum, 7–11 AM ET, $1–20 up 10%+ on 5x vol, TCS 750+ |
| orb_scanner | observer | 120s | Opening Range Breakout, 8:30 AM–12 PM ET |
| extended_scanner | observer | 1800s | Layer 4 multi-day swing: EMA50 pullbacks, breakout holds, gap continuations |
| crypto_scanner | observer | 180s | 24/7 XRP/ETH/SOL; SCALP/SWING/DCA from RSI, Bollinger width, volume |
| forex_scanner | observer | 180s | Majors via Kraken OHLC. **DORMANT** — Alpaca has no FX venue, so it skips rather than manufacture guaranteed vetoes |
| options_scanner | actor | 1800s | The Wheel (CSP/CC) + options ideas. 2,753 lines. Pricing modeled (Black-Scholes) |
| risk_manager | observer | 0 (event) | Highest authority. Approves/vetoes every signal; Adaptive Scope, kill-switches, market filters |
| portfolio_architect | observer | daily | Bootstrap edge test, optimal-f sizing, HRP allocation, CUSUM structural break. Proposes only |
| trade_execution | actor | 0 (event) | Routes approved signals — stocks to Alpaca paper, crypto to internal engine |
| position_monitor | actor | 60s | Watches every open position; stop/target closes, day-trade management, Alpaca fill reconciliation |
| tax_optimizer | observer | 1800s | Tax impact of every executed trade |
| kindrip_agent | actor | 21600s | Layer 7 — scheduled contributions into children's Future Index Accounts, auto-invested |
| market_sentiment | observer | 1800s | Watchlist news, sentiment scoring, material-event flags |
| research | observer | 1800s | Earnings + ex-dividend calendar warnings |
| adaptive_scope | observer | 600s | Reads regime + breaking news, adjusts strategy scope within guardrails |
| user_support | observer | 0 | Answers questions about decisions, blocked trades, outcomes |
| strategy_discovery | observer | 3600s | Win/loss metrics; flags a review every 25 trades |
| dividend_manager | actor | 21600s | Credits modeled distributions, reinvests (DRIP) |
| dividend_lt_agent | observer | 1800s | The Dividends (Long-Term) lane — see §7 |
| broker_truth_agent | observer | 900s | Asks Alpaca what options it actually holds, makes the ledger agree — see §5 |
| market_horizon | observer | 900s | Cross-asset landscape: stocks, crypto, gold, USD, bonds, income ETFs |
| cycle_awareness | observer | 6h | Earnings + ex-div dates per ticker; tags signals with cycle context |
| exit_advisor | observer | 300s | Held-too-long pattern: alerts when a position gives back 30%+ of peak gain. Never closes |
| exit_advisor_options | observer | 300s | Options edition. Contract-count drives target (1–10 → 30–50%, >10 → 15%), drawback ladder 39/30/25%, catalyst urgency bump |
| ops_watchdog | observer | 300s | Registry vs expected-agent list, last-tick times, **approval-starvation alarm** — see §6 |
| book_health | observer | 300s | Per book: unmanaged notional, positions past their own stop, halts whose condition cleared. Alerts out via webhook |
| relay_ingest | observer | 300s | Drains Nova's skill briefings from `relay_briefings`, validates, files into shared memory. Context only |
| market_desk | observer | 300s | Digests the newest `market_context` brief into ONE MarketView via `current_market_view()`. Consumers may only TIGHTEN on it |
| archivist | observer | 900s (gated) | Hourly bundle → Supabase Storage; weekly → Dropbox (deliberately a different vendor) |

Design intent worth preserving: **observers propose, the Risk Manager decides, actors
execute.** Portfolio Architect and both Exit Advisors are explicitly advisory — they
propose and alert, never actuate. Market Desk holds no opinions and moves no levers.

---

## 3. The wiring you are being asked to verify

The user-visible question Mike is asking is: *are the wires and attachments actually on,
and does the logic go all the way through?* The honest answer today is "mostly, with a
known history of things that looked on and were not." What follows is the map.

**Signal path (the one that matters):**

```
scanner agent (observer)
  → bus message kind="signal"
    → risk_manager.on_message ── kill-switch gate → market filter → adaptive scope
                                  → confidence bar → R:R floor
      → bus message kind="approve" | "veto"
        → trade_execution.on_message
          → route_guard / bind_for_user  (which book?)
            → Alpaca paper order  |  internal crypto paper engine
              → position_monitor  (fills, stops, targets)
                → paper ledger (paper_positions) → dashboard
```

Two independent alarms sit across this path so a silent break cannot last again (§6).

**Dashboard → engine:** the Next.js route handlers read Supabase directly
(`web/src/lib/supabase`, `web/src/lib/services`). `web/src/app/api/agents/*` exposes the
agent roster, feed, per-agent toggle, trigger and run-now. `web/src/app/api/wheel/*`,
`/api/paper/*`, `/api/stocks/reconcile` reach into ledger operations.

**Nova → engine:** scheduled cloud sessions post briefings through `ops/relay.py brief`
into `relay_briefings`; `relay_ingest` drains them; `market_desk` digests them. Deploys
and restarts queue through `ops/relay.py` as well (six CHECK-constrained job kinds).

---

## 4. Book isolation — Mike's standing architecture rule

Stated 2026-08-27, in his words:

> "Every single book or account should be treated as its own when it comes to the broker —
> we would not want something to happen on the main account affect the retirement account.
> I would not want it to interrupt each other in general."

This is future-stakes: the account set will someday include a retirement account, so any
shared state that lets book A's condition change book B's behaviour is a defect **even
while all three books are paper**.

**How to apply:** any state, gate, counter, cache, settings read or halt not keyed by
`user_id`/book is suspect. Grep module-level mutable state and ask "whose is this?"

**The recurring disease — measurement per book, enforcement global.** A per-book number
computed correctly, then collapsed into one verdict that speaks for everyone. Found five
separate times:

- **2026-08-09** — one global credential; every book's orders would have hit the primary's
  Alpaca account. Fixed: accounts registry + `bind_for_user` + `route_guard` refusing
  unresolved books.
- **2026-08-18** — `get_bot_settings()` with no book fell back to "most recently updated
  row", so one book's toggles governed all three. Fixed: per-book reads at the fan-out,
  `book_gate.admits`.
- **2026-08-18** — `consecutive_loss_limit` read once outside the loop.
- **2026-08-20** — open-signal capacity counted all books in one bucket against one book's
  cap. 516 entries died in a day.
- **2026-08-27** — `check_all`'s single-user assumption: the primary's −8.0% week vetoed
  1,162 signals across all three books. Fixed: `check_states` per book, per-book
  enforcement at risk and at the fan-out. Broker-reject and slippage counters were
  process-global; fixed in `0e6b241` (unattributed entries count toward every book, which
  is the conservative direction).

**Related policy, same date.** The WEEKLY loss limit is **RECOVERY mode, never a full
stop**: suspend speculative lanes, half size, +10 TCS, stops 25% tighter, auto-clears on
claw-back. Daily 3%, streak, reject and slippage halts remain hard stops for their own
book. Knobs live in `killswitch.py` (`RECOVERY_*`) and were chosen by Mike explicitly —
changing them is a behaviour change needing his sign-off.

Recovery is also treated as a *learned skill* (Mike, on the sub-$5k book's comebacks:
"they can get past and make it forward"). `check_states` records
`recovery_entered`/`recovery_completed`; completions write a Mem0 note so the experience
survives restarts.

---

## 5. Broker truth — how the ledger is kept honest against Alpaca

This section describes two opposite failures with the same root cause. Read it before
touching anything that reads broker positions.

### The phantom-expiry incident (2026-08-21 → 23)

Four short puts expiring Friday 2026-08-21 sat `status='open'` in `paper_positions` all
weekend. They had expired worthless; Alpaca had already dropped them. The engine logged
`route_orphan` repeatedly ("ledger says acct3 but acct3's broker doesn't hold it") —
correctly refusing to act on unverifiable positions, but *refusing forever is not
resolving*. Under the dividend lane's hard collateral rule those dead contracts read as
cash still reserved, withholding buying power on two books.

Reconciled by hand 2026-08-23 after checking Alpaca directly: BMY260821P00061000,
AGNC260821P00010500 (×2 rows), T260821P00023000 — all `closed_expired`, all confirmed OTM
at Friday's close, no shares assigned. Two rows correctly left open
(AGNC260828P00010500, PG260828P00138000), both confirmed held.

**Why nothing caught it** — two defects in
`paper/stocks_reconcile.detect_option_drift_all_users`: (1) zero call sites, nothing had
ever invoked it; (2) it counted rows in `options_positions`, which holds ZERO open rows,
because **option positions actually live in `paper_positions` with
`asset_type='option'`**. Even wired up it would have compared the broker against an empty
table and mis-flagged everything.

> **Remember this: option rows live in `paper_positions`, not `options_positions`.**

**The fix** (commit `0f4eaa2`): `agents/app/paper/broker_truth.py` plus a dedicated
`broker_truth_agent` on a 15-minute tick. Per book it asks Alpaca what it actually holds,
then:

- **CLOSES only the unambiguous case** — past expiry AND underlying settled out of the
  money AND nothing to move → `closed_expired`, realized = premium kept (short) / lost
  (long).
- **FLAGS everything else**: expired ITM = likely assignment (shares and cash move, never
  guessed); not expired but missing at broker = ROUTING INCIDENT needing a human; no price
  = cannot tell = untouched; broker holds an option the ledger lacks = flagged for
  adoption, never invented.

The asymmetry is the design. Two safety properties to preserve if this is ever edited: a
FAILED broker read returns `None` and takes no action, and it binds with `bind_for_user`
(reading unbound compares every book against the primary account). 10 tests in
`agents/tests/test_broker_truth.py`, including a replay proving the reconciler reaches
unaided the same verdict reached by hand.

### The inverse incident — the phantom-CLOSE loop (2026-08-28)

Symptom: a "$14,453 UNMANAGED" alert. The broker HELD AMZN/DOT/QYLD on the 75k book while
the ledger kept closing them — the phantom was in the CLOSES, not the positions.

The loop:

1. `alpaca.get_positions()` collapsed every failed read (429/timeout) into `[]` —
   indistinguishable from a flat account.
2. `book_scope` cached that `[]` as broker truth for the tick.
3. Position Monitor's fill detection read "symbol gone at broker" as "the bracket/external
   sell filled" and closed every broker row on the book at MODELED prices (bus reasons
   `alpaca_bracket` / `alpaca_external`; rows closed seconds apart is the signature). It
   hit the primary book too: XLE/GOOG/SPCX.
4. `stocks_reconcile` (correctly bound and guarded) re-adopted them. Repeat.

DOT cycled 8× over four days, booking ~−$5.8k of phantom realized P&L into the account
counters.

**Second bug in the same loop:** the ledger rounds quantity to 8 decimals (UP) while
Alpaca holds 9, so every crypto stop placement 403'd "insufficient balance" (requested
13060.38462492 vs available 13060.384624917) and $10.9k of DOT rode with no floor. The
round-DOWN twin is why dust crumbs (3e-9 DOGE/LTC/SOL) sit on the other books.

**The fix:** `get_positions_strict()` (returns `None` on failure) and `book_scope` uses it
— both Position Monitor branches already treat `None` as do-not-act. `ratchet_crypto_stop`
clamps the order qty to the venue's own qty STRING. Tests:
`agents/tests/test_broker_read_strict.py`.

> **THE LESSON, NOW LEARNED THREE TIMES** (stocks_reconcile 6/15, broker_truth 8/23,
> book_scope/monitor 8/28): every broker read that can trigger a destructive action must
> distinguish "failed" from "empty". Grep new callers of `get_positions` for this before
> trusting them.

Follow-up still owed: unwind the phantom realized P&L from the 75k/primary counters; the
ledger's 8dp quantity storage (column or writer) is still un-fixed at the source.

A separate Alpaca spelling trap, learned 2026-08-29: the ORDERS endpoint takes `"DOT/USD"`
but the POSITIONS endpoint takes `"DOTUSD"`. Commit `1faac42` passed all 28 guard suites,
booted clean and changed NOTHING because the crypto-stop qty clamp probed
`/v2/positions/DOT%2FUSD`, which 404s, and the `except` swallowed it. Fixed in `ed240ed`.

### Still riding on another agent

**The Wheel (CSP/CC) lives inside `options_scanner.py`** — 2,753 lines with wheel logic
woven through cooldowns, greek filters, allocation buckets and OCC matching. Mike asked
(2026-08-23) that dividend/wheel work not overload existing agents. The ladder and
reconciliation now have dedicated agents; **extracting the Wheel is a real project needing
a careful dedicated session, NOT blind surgery on the agent that places live option
orders.**

---

## 6. The four-day outage, and the two nets built because of it

**This is the most important operational story in the project.** It is why the house rules
in `CLAUDE.md` read the way they do.

### What happened

**2026-08-27 12:36 ET → 2026-08-31 13:08 ET: ZERO approvals in four trading days.**

Commit `8c6c5ea` (per-book kill-switches) added `recovery_bump` into risk_manager's
confidence-bar sum at line 774 while writing the block that ASSIGNS it 150 lines below at
930. Every signal carrying a real direction raised `UnboundLocalError` inside
`on_message`. `bootstrap._route` caught the handler exception and logged
`agent.on_message.failed` **to stdout only** — no bus message, no activity row, no alert.

Fixed in `6d633ad` by moving the whole per-book gate above the bar, where a gate belongs
anyway. Full write-up: `C:\Trezo\reports\incident-2026-08-31-approval-outage.md`.

### Three lessons, now house rules

1. **The log looked QUIET, not broken.** The checks ABOVE the crash kept emitting, so every
   surviving message was a "Neutral direction" veto — which a flat tape explains perfectly.
   **When a lane goes silent, count APPROVES, never just look for errors.**
   `trade_execution: msgs=0` in `report_status` was the tell, visible four days early.
2. **The 10 tests shipped with `8c6c5ea` pinned kill-switch POLICY as a pure function and
   never ran a signal through `on_message`.** Green suite, dead pipeline — the platform's
   own dominant defect class, committed inside the fix for it. **A change to an agent's
   message path needs a test that exercises THE PATH.**
3. **A swallowed handler exception is invisible.**

### The two nets (commit `d9512e1`, 2026-08-31, deployed 18:37 ET, verified live)

Deliberately independent, because the first only catches crashes and the outage class is
bigger than crashes.

**NET 1 — a swallowed handler exception is ANNOUNCED.** `bootstrap._route` now calls
`_announce_handler_failure(state, message, exc)` (bootstrap.py lines ~128–143), which:
publishes to the bus (`kind="error"`, `event="handler_failed"`, carrying the failing
agent, exception type + message, the triggering agent/kind/ticker, and an occurrence
count); writes an activity-log line (survives a bus/Supabase outage); and pings the webhook
ONCE per (agent, error) — a crash repeats on every message and nobody needs a thousand
pings; one is what four days were missing.

Two invariants, both pinned by guards: (a) the report is published AS the failing agent,
because `_route` skips the sender — that is what stops a handler which crashes on
everything from crashing on its own crash report; (b) every step is wrapped in try/except
— a reporting bug must never become the second outage.

**NET 2 — APPROVAL STARVATION, and this is the one that matters.** `ops_watchdog` counts
signals / approves / vetoes / handler_failures off the bus in `on_message` (free: tallies
only, no I/O, unbreakable — pinned by a guard that feeds it a message whose payload
raises). On each 5-minute tick `_check_flow()` asks the question the outage would have
failed: **did anything get APPROVED?**

Alarms when: market hours AND ≥ `FLOW_MIN_SIGNALS` (15) signals AND window ≥
`FLOW_WINDOW_MIN` (20) min AND zero approvals. The alert names the SHAPE — vetoes account
for them (a posture/config problem) vs "NO verdict at all" (a crash) — and fires urgent in
the second case. Every reason to stay quiet is pinned by its own guard: thin flow, short
window, closed market, and one approval is enough. Env-tunable:
`TREZO_FLOW_WINDOW_MIN`, `TREZO_FLOW_MIN_SIGNALS`.

**Net 2 does not care WHY nothing trades** — it also catches a gate stuck closed or a
config that vetoes everything, neither of which raises an exception at all. That is the
point.

**Guards:** `agents/tests/test_silent_failure_nets.py`, 15 tests. Three of them pull the
REAL `_route` and `_announce_handler_failure` out of `bootstrap.py` with `ast`, exec them
against stub bus/registry, and drive a handler that raises this outage's exact
`UnboundLocalError` — then assert the message reaches the bus. Reading source proves code
EXISTS; the whole failure class here is code that exists and does not BIND. (Booting the
real engine in a test is out of the question — it would wire 30 agents to live broker
keys.)

**Related guard:** `agents/tests/test_risk_manager_signal_path.py` reads `risk_manager.py`
with `ast` and asserts every bump/reason in `on_message` is assigned before it is read, and
that the kill-switch gate stays above the bar. Static on purpose — the deploy gate cannot
execute the real handler (needs Supabase, bus, keys) but it CAN prove the ordering
invariant.

**How to use them when diagnosing:** when a lane goes silent, do NOT look for errors first
— **count approves**. `ops/relay.py queue report_status` showing `trade_execution: msgs=0`
during market hours is the tell. Then check for `handler_failed` on the bus
(`agent_messages` kind=error) before assuming a market or posture explanation.

Verified post-deploy 22:37–22:50Z: `handler_failed` = 0, `approval_starvation` = 0
(correct — market closed is never evidence), ops_watchdog ticking, risk_manager emitting
normally. **The first live market-hours exercise of Net 2 was the next session's open: it
must stay SILENT while approvals flow.**

---

## 7. The Dividends (Long-Term) lane

Spec: `docs/strategy/DIVIDEND_LT_PARAMETERIZED_SPEC.md` (committed 2026-08-22). It is
capital-agnostic — every dollar figure is a parameter.

**Its design invariant, from Mike's own book:** six positions, one wrapper class — cash
yield 17.6% near-uniform, total return −17.0% to +22.6%. The payout carried NO information
about the outcome. **THE LANE'S JOB IS A NARROWER SPREAD, NOT A HIGHER MEAN.** Never
"improve" this lane by raising expected return; that is the mistake it exists to correct.

### The gate problem (fixed 2026-08-22, commit `41e5499`)

Mike: *"analyze it for market wide and not a default list only."* The Wheel's candidate
POOL was already market-wide, but the quality GATE was a ~40-name dict with an Alpha
Vantage fallback (5 calls per build against a 25/DAY tier), so unlisted names effectively
could never qualify.

> **THE GATE IS WHAT DECIDES, NOT THE POOL.** Remember this shape; it recurs.

Coda 2026-08-27 (`d1becae`): the AV fallback is GONE everywhere — the yield fallback now
computes trailing yield from broker corporate actions (no daily cap, split-adjusted, 24h
cache).

### The screen

`agents/app/strategies/dividend_screen.py` implements spec §4 against Finnhub metrics
(60/min), cached in Supabase `dividend_screen_cache` (migration 0057) for 7 days; coverage
RATCHETS.

**HONESTY RULE: a check that could not be evaluated is UNVERIFIED, never "pass".**
UNVERIFIED names are skipped, not admitted on optimism.

Since `2c8c10d`/`eb271bb` the screen runs DIFFERENT tests for companies vs funds:

- **Companies**: yield ≥ 1.5%, payout ≤ 70%, raise streak; and a cut READMITS after
  recovered + rising + 3 healed years (Mike 8/24: *"do not cut... if we can get in at a low
  price until 2030 we will be building positive net income"*).
- **Funds**: trailing distribution ≤ trailing total return (the eating-NAV test), no
  reverse split in 24 months, $2M ADV floor. A raise streak is the wrong instrument for a
  variable-by-design distribution — JEPI passes, NVDY fails.

The dividend-history layer is the broker's corporate-actions feed
(`app/data/corporate_actions.py`): split-adjusted BEFORE any year-over-year compare;
specials (≥3× median) and fragments (<1/3 median) filtered; forward ex-dates included
(the guard's whole point).

### Tiering and the rules that bind

Tiering drives lane rule #4: **GROWTH** (yield < 4%) never writes covered calls;
**HIGH_YIELD** (≥ 4%) wheels freely. Since `d1becae` rule 4 is LIVE in two places: the
wheel advisor's tier check (real screen tier, not `None`) and a CC-overlay skip on
confirmed-GROWTH lots.

The advisor also binds rule 3 (ex-date guard, real ex-dates), rule 5 (ledger-honest
collateral, fed the collateral gate's own numbers) with defer-or-SHRINK, the earnings
blackout (cycles feed), and judges the ACTUAL submitted OCC. The reevaluator EXEMPTS
dividend/wheel/income rows — its price-only losers-only lens read ex-div NAV drops as
failure. Allocation routes `dividend_lt` to the INCOME pocket (it was previously sized
from income but funded from stocks).

### Lane modes (migration 0058, applied 2026-08-27)

`bot_settings.dividend_lane_mode` (ACCUMULATE | INCOME | PARTIAL) +
`dividend_lane_partial_pct` exist and the agent's SELECT actually fetches them. (It read
the column before any migration defined it — the lane was permanently ACCUMULATE until
8/27.) §6 INCOME draw = min(actual distributions, 90% of trailing 12-month total return);
PARTIAL draws `partial_pct`% of that. Flip per book in the DB, no deploy. Code falls back
to the old SELECT shape if the columns are missing.

### Modules

- `dividend_screen.py` — §4 + `sector_capped()`; REIT+BDC share one factor
- `dividend_lt.py` — §1 guardrails (REFUSE, never clamp); §2 sizing; §3 state machine +
  U1–U4; §5 explains-never-actuates readout; §6 projection + INCOME draw
- `dividend_lane_rules.py` — rules 1/3/5
- `dividend_lt_agent.py` — 30-min tick: sizes each book's lane from its income pocket,
  screens market-wide, sector-caps, proposes ladder entries; signals only — Risk Manager
  judges; max 2 entries per tick

### Test-zero and what's unbuilt

Probed 2026-08-27: Alpaca `/v2/account/activities` WORKS on all three books and returns 0
DIV rows so far — the real verdict is the ladder's first pay date, ~mid-September 2026. If
paper never credits, synthesize credits tagged `simulated_cashflow`, flagged, never
hidden. The two-ledger reconciliation (dividend_manager writes `user_positions`; the lane
holds `paper_positions`) is deferred until that verdict.

**STILL UNBUILT:** UI for §1 inputs and the §5 readout; §7 measurement rails (forecast
MAPE, recycling ratio ≤ 1.0, TR vs 50% SPY / 50% SGOV, forward income per $1k); rule 1's
enforcement point; U1/U2 consumers (premium laddering).

Calibration constants `LADDER_YIELD = 5.3%` and `WHEEL_TR = 8.0%` are **UNPROVEN
placeholders** — replace them with measurement (a 12-month verdict gate), never tune them
to hit a target. The kill-switch baseline is still realized-P&L-only; making it
total-return aware is Mike's decision, parked deliberately.

---

## 8. The Wheel's delta gap

Found 2026-08-29. Both the Dividend LT lane and the Wheel size on `wheel_delta` (default
0.25, guardrail range 0.15–0.40; §1 calls it "the ONLY input that changes E[return]") —
and **Trezo has never selected a contract by delta, or measured one.**

The chain of disconnection, in order:

1. `wheel.py:73-74` — `CSP_OTM = 0.05` / `CC_OTM = 0.05`. Strikes are placed at a FIXED 5%
   out-of-the-money, `TARGET_DTE = 30`. Delta plays no part in choosing the target.
2. `alpaca_data.live_option_pick()` scores real contracts by
   `(abs(strike - target_strike), abs(expiration - target_exp))` — strike distance first.
   Delta is not consulted here either.
3. `LiveOption` carries only `occ, strike, expiration, premium`. No delta, gamma, IV, open
   interest, or bid/ask. **The live chain is fetched and the Greeks are discarded.**
4. Delta is then ASSERTED from `dividend_lt.DELTA_TABLE` — five hardcoded rows
   (0.15/0.20/0.25/0.30/0.40) mapping delta to `prem_mo`, `blended_tr` and `assign_prob`.
   Its own comment says "UNPROVEN pending live chain data". Note `assign_prob` is set equal
   to delta in every row — the textbook rule of thumb, never tested.

So the open question has a precise form: **what delta IS a 5%-OTM 30-DTE put on the
22-name wheel bench?** Nobody knows; it certainly varies by name (a REIT and INTC will not
match); and 0.25 is a number nothing has ever checked. First real measurement, 8/29: KO's
5%-OTM 30-DTE put ran ~0.19 delta, not the asserted 0.25.

The "pending live chain data" comment MISLEADS — it implies the data is unavailable. It is
not; Trezo pulls live chains and quotes from Alpaca on every auto-fire. What is missing is
reading delta OUT of the chain it already has. Same BUILT-BUT-NOT-BOUND shape.

**Consequence:** `wheel_delta`, `PREM_RATE_AT_025 = 0.0060` and the whole `assign_prob`
column are fiction against live pricing. Likely also the root of the variance-premium
observer reporting nearly the entire wheel pool as CHEAP (`wheel.py:299-326`) — the go/no-go
is made on modeled premium at an assumed delta.

**Cheapest fix, no new vendor:** have `live_option_pick` carry the Greeks Alpaca already
returns, select on delta rather than strike distance, and let measured values replace
`DELTA_TABLE`. Then `WHEEL_TR = 8.0%` can be measured instead of assumed.

---

## 9. QuantConnect — a lab and a supplier, never a replacement

**Mike's standing frame (2026-08-29):** QuantConnect is to EMPOWER Trezo, not replace it.
Do not propose migrating agents, porting lanes, or changing anything in Trezo. Find ways QC
supplies data, testing, strategy creation and information Trezo lacks. Trezo stays as it
is.

**Practical status:** superseded in practice by
`docs/workspace/TREZO_MEASUREMENT_PROGRAM_V2.md` (2026-08-29) — Mike cannot use the LEAN
CLI without a business account, so the measurement program was rebuilt on Alpaca +
Treasury rails Trezo already has wired. Treat QC as optional.

What QC would have supplied, if it is ever revisited: the US Equity Option Universe
dataset — daily Greeks, implied volatility and OPEN INTEREST for 4,000 underlyings back to
2012, free in their cloud, returned as a pandas DataFrame. That is what would retire
`DELTA_TABLE`, `PREM_RATE_AT_025` and the never-measured `wheel_delta`. Caveats: values are
previous-day-close from QC's forward-tree model (right for calibration, wrong for an
intraday decision), the licence forbids piping raw data into other applications (derived
measurements are the defensible channel), and LEAN's default assignment model has NO
ex-dividend logic at all, so any assignment statistic on a dividend payer is an undercount.

**The framing to keep:** Trezo is not short of DATA — it has live Alpaca chains on every
auto-fire. It is short of **EVIDENCE**: a measured delta, a measured total return, a
measured assignment rate, a benchmark it has never been compared against. And the
measurement work is INDEPENDENT of the binding work — a better delta table does not help a
per-name cap that gets overwritten before it is read.

---

## 10. The 52-item audit and what actually holds

**Read this before trusting any "fixed" claim about Trezo.**

On 2026-08-27 an audit found 52 items at commit `e08649d`. Commit `d1becae` claimed to fix
22 of them the same pre-open morning. A second-pass ADVERSARIAL VERIFICATION against the
code at `229b1ee` found that **8 claims hold, 7 hold in part, 6 do not bind at all, and 8
new problems shipped.** Do not treat the clear-out's "22 fixed" as accurate.

Then the 2026-08-28 after-close batch (`4ee6e5b` → `6c7e57f` → `c0c7666` → `a91dc97`)
closed the root cause and most no-bind items. And, worst of all, one of the clear-out's own
commits silently stopped the platform trading for four days (§6).

**Artifacts, in order** (Cowork artifacts; the third is authoritative):

- Original 52-item audit — `https://claude.ai/code/artifact/5ce5f978-500a-4cb7-a4fb-666016b40675`
- The clear-out's own claims (`d1becae`) — `https://claude.ai/code/artifact/bb9f31ef-f2b1-4fea-937b-a760f03ba0a3`
- **THE VERIFICATION, the authoritative one** — `https://claude.ai/code/artifact/47c9432b-10df-404d-a9c6-44a2d718a6f7`
  (checkpoint `229b1ee`; everything below tracks HEAD past it)
- QuantConnect supply lines — `https://claude.ai/code/artifact/2c16ad57-01cf-4854-a823-19da5b9d9aae`

### What the verification CONFIRMED holds

30-agent watchdog roster; migration 0058 (applied 8/27, seeded 58/58); market briefs freed
from the janitor gate; advisor judges `pick.expiration`; dead seed-rotation deletion;
BACKUP-USB `.env` exclusion; repo history CLEAN. All three books live and FILLING
(8/31 17:12Z: SOL on all three, LTC on two).

### Fixes shipped 8/27 PM – 8/28 AM

- `e96cb0f` — double-restart + accumulating scheduled tasks fixed (unique one-shot task;
  ONE boot per deploy since).
- `0e6b241` — `killswitch.py` docstring lie fixed; per-book reject/slippage halts.
- `06ab0ab` — **silent-scanner ROOT CAUSE**: the scheduler's 900s tick ceiling was
  CANCELLING every `options_scanner` tick once the wheel pass outgrew 15 minutes. Fixed
  with per-agent `tick_timeout_seconds` + bus-visible `tick_cancelled_timeout` /
  `tick_failed`.
- `fb190b6` — `_step`'s undefined `log` NameError in options_scanner.
- `c4ab998` — scanner tick steps isolated so a failing/hanging step cannot silence the
  agent.
- `8c6c5ea` — per-book kill-switches + weekly RECOVERY mode + per-book counters. (Note:
  8/28's "zero kill-switch vetoes all day" was NOT proof this was healthy — the outage
  meant nothing reached that code.)

### After-close batch 8/28 (deployed, `send_test` proven live)

- `4ee6e5b` — `TREZO_ALERT_WEBHOOK` loaded via Settings. **The alert channel worked for the
  first time ever** (`{ok:true}` from the server 16:33 ET; first real alert delivered 8/28
  22:08).
- `6c7e57f` — `max_notional` through the approve whitelist + `_lane_cap_f` in BOTH Alpaca
  sizing paths; `venue_fallback_modeled` on the reachable path; EXACT `"dividend_lt"`
  prefix.
- `c0c7666` — per-agent tick ceilings from observed cancellations.
- `a91dc97` — BACKUP-USB purge can never target `C:\Trezo`; REBUILD doc names the one-time
  rotation; laptop twins synced.

### Weekend batch 8/29

`34b8065` (rolled back by the deploy gate — pytest fixture) → `1faac42` (green, changed
nothing — wrong URL spelling) → `ed240ed` (the actual fix) → `3dceace` (measurement program
v2, generalized off QuantConnect).

### STILL OPEN — HELD FOR MIKE (decisions, not code — do not resolve these unilaterally)

a. **R:R floor vs learned targets.** As of 8/31 every equity approval dies at execution:
   *"Reward:risk 0.4 below your 0.5 floor"* — 6 for 6 (WMT/INTC/RBLX/PYPL/NVDA/AAPL). The
   learned-target shrinker sets ~0.6% targets against ~1.5% stops. Two legitimate controls
   disagreeing. Crypto is unaffected and trading. **This is the highest-value open item:
   the equity lane is effectively not trading.**
b. Wheel advisor defer-or-shrink redesign — the shrink branch is mathematically
   unreachable; the CSP path only ever requests 1 contract.
c. INCOME/PARTIAL wire-or-refuse (dividend lane modes).
d. Nova relay STEP 2B structural fix: anon-key RLS insert vs a fallback poster.
e. **ONE-TIME Alpaca + Supabase key rotation — still NOT done.** Pre-08-27 USB backup
   passes carried real keys.
f. QYLD naked-call alert semantics.
g. (Now shipped as Net 1, but the policy question of what else should announce itself
   remains open.)

### STILL OPEN — P2 sweep

- Phantom-P&L cleanup in the realized counters (DOT ~−$5.8k booked that never happened).
- Crypto dust crumbs (3e-9 DOGE/LTC/SOL) firing "$0 UNMANAGED" alerts.
- LTC "potential wash trade detected" 403s when an opposing order rests.
- Advisor's cold Finnhub calls in the pre-submit hot path degrade to ALLOW on rate-limit.
- Reevaluator exemption narrowness — Risk Manager injects a hard 5% stop regardless;
  `no_price_stop` is read by nothing.
- Ideas universe double-build.
- Cycles empty-cache-24h.
- Advisor collateral 0.0 default.
- `dividends/schedule.py` still on Alpha Vantage.
- Pocket seats-vs-dollars.
- Briefs latch-before-await + EDT-only math.
- Archivist `enabled()` bare `getenv`.
- `PROJECT_STATUS.md` body still reads June in §2/§6.
- Sitemap says 21 agents (there are 30).

### Method notes that stay true

- **BUILT BUT NOT BOUND is the house failure mode, and it survives its own remediation** —
  three times now: the clear-out's headline feature shipped green and unreachable; the
  crypto qty clamp shipped green and probed a 404; and `8c6c5ea` shipped green and stopped
  all trading. Grep CALL SITES, check what values actually arrive, ask each guard when it
  last fired.
- Verify a fix by reading the RESULTING FILE in context, never the diff alone.
- Watch the LIVE LOG for the symptom to stop before reporting a fix as working.
- Session memory drifts behind the repo. Clone from GitHub `main` first.
- Trust call sites over docstrings here.

---

## 11. Environment, deploy and operations

### Machines

- **Laptop `Mike-2MM-Trezo`** is the primary machine (the old PC was sold 2026-08-21).
  Working copy: `C:\Trezo\trezo-platform`. `D:\Trezo` is a UnionSine USB drive (117 GB),
  backup only.
- **Trezo-Server** — Tailscale `100.115.119.32`; RDP to `98.81.100.112`, user
  **`Adminastrator`**. *The username is misspelled ON PURPOSE — that is the literal account
  name; "correcting" it breaks authentication. Never normalize it.* Mike knows the password
  independently.
- Service ports 8000/8001/3000 do not answer on the PUBLIC IP by design (firewalled) but DO
  answer over Tailscale.

### Toolchain (final state after the 2026-08-21 migration, commit `0cae7db`)

git 2.55.0, node v24.19.0, npm 11.17.0, python 3.12.10. All three `.env` files present
(`agents/.env` ~49 keys, `api/.env`, `web/.env.local`); `agents/.venv` rebuilt; root
`node_modules` via `npm ci`; web on the next 14.2.x security patch; typecheck green in both
workspaces. A half-started Next 16 upgrade was reverted — upgrading remains a deliberate
future project (React 19 + async `cookies()` at 6 call sites).

**Watch item:** `mem0ai` (unpinned, resolved 2.0.7) pulls pandas 3.0.5 / numpy 2.5.2 while
`yfinance` is pinned 0.2.40 (predates pandas 3.0). Pandas errors in market-data pulls →
bump yfinance.

### The deploy gate

**`agents/tests/run_all.py`, NOT pytest.** Every `git_pull_restart` runs the guard suites
on the server BEFORE restarting and ROLLS THE CHECKOUT BACK if any suite fails — it did
exactly that to commit `34b8065`, whose new guard file used pytest's `monkeypatch` fixture.

`run_all` imports each `tests/test_*.py` and calls `_bootstrap.run_tests` on its namespace:
plain `test_` functions, NO fixtures, no pytest, no `.env`, no network. A new guard suite
must call `_bootstrap.stub_config()` then `load_module("app.x.y")`, and patch module
attributes itself (use a contextmanager that always restores them) — see
`tests/test_broker_read_strict.py`.

Run BOTH gates locally before pushing: `python3 -m tests.run_all` (the one that decides)
and pytest.

### Deploy and restart

Deploys queue via `ops/relay.py` (deploy / restart / rebuild etc., six CHECK-constrained
kinds). **A deploy is DONE only when the boot beacon says so** — every boot writes
`engine_boot` (pid, commit, agents); `relay.py watchboot` or `relay.py log --event
engine_boot` confirms. Job rows saying "done" mean the PULL happened, nothing more — and
after a guard rollback the row STILL says done, so read the result body for "ROLLED BACK".

The detached self-restart is proven live (`e96cb0f`: unique one-shot `schtasks` task
`TrezoRelayRestart_<HHMMSS>`, single +2min trigger, no `/Run`, legacy End+Delete). Expect
the beacon ~6–7 min after queueing. nssm printing "Unexpected status
SERVICE_START_PENDING" during a manual restart is NORMAL — Python takes ~40s to boot; trust
the beacon, not nssm.

`AUTO-PULL.ps1 -Register` has still not been run on the server (standing ask).

### Watchdogs on the server

Two Windows scheduled tasks guard the tiers: `TrezoWebWatchdog` (`web-watchdog.ps1`, port
3000 only, repair ladder + `.next` cache clear) and `health-watchdog.ps1` for the engine.
**They must never both touch the engine, or two engines could land on one Alpaca account.**

### Database

Supabase DDL cannot be run by an agent (no Postgres password; PostgREST does no DDL).
Migrations are pasted by Mike into the SQL editor; since 0058 the `schema_migrations` table
records what ran. 58 migrations plus three DIAGNOSTIC scripts in `db/migrations/`.

### Backup / restore

`BACKUP-USB.ps1` (one-click via `RUN-USB-BACKUP.cmd`) FINDS the stick (marker / label /
rebuild-doc — the drive letter is not assumed), mirrors `C:\Trezo` → stick,
`/XF`-excludes `.env*`, PURGES any `.env*` an older pass left, writes sanitized
`*.template` files (key names only), and drops `RESTORE-FROM-USB.cmd` at the stick root.
Restore = double-click that `.cmd` on any PC: it copies back, recreates each `.env` as an
empty skeleton, and prints the keys to refill from the password manager. **The stick is
secrets-free by design.**

### Scheduled Nova reports (cloud sessions, not part of the engine)

Pre-Market 8:00 AM ET, Midday 1:00 PM ET, Pre-Close 3:00 PM ET. Each emails Mike, refreshes
a market-movers dashboard artifact, and posts a `market_context` brief to the engine via
`ops/relay.py brief`. Crons are UTC on EDT offsets — **they DRIFT an hour when EST returns
in November; fix the crons then.** STEP 2B posts via the laptop bridge and MISSES when the
desktop app is closed at fire time (that is open item (d) above).

---

## 12. "A running trading site for users" — where that actually stands

Mike's stated goal for this audit is a trading site users can run on. Here is the honest
gap, so nobody has to rediscover it.

**What exists and works today:**

- Supabase auth with sign-in / sign-up / forgot-password / reset-password / OAuth callback
  (`web/src/app/(auth)/**`, `/auth/callback`, `/auth/sign-out`).
- RLS policies from migration 0002 onward, with an `initplan` optimization pass (0042) and
  a security lockdown pass (0041).
- An onboarding flow (`/onboarding`, `/onboarding/tour`).
- Per-user broker connections with an OAuth framework and token refresh
  (`0026_broker_connections`, `0031_broker_token_refresh`,
  `/api/brokers/[broker]/authorize|callback|disconnect`,
  `/api/cron/refresh-broker-tokens`, `/api/internal/broker-token`).
- An owner/account split (`0045`) with book tables repointed to accounts (`0047`) and
  watchlist items account-scoped (`0048`) — the schema-level groundwork for more than one
  owner.
- ~40 dashboard pages and ~50 route handlers, including admin-only routes
  (`/api/admin/*`).
- Terms and privacy pages.

**What has never been exercised:** the platform has run for one owner across three of his
own books. Every "per user" mechanism above is, in practice, per *book* for one person.
The parts that would fail first with real users are, in expected order:

1. **The engine's user fan-out.** The engine ticks agents over a set of books resolved from
   the accounts registry (env-var slots `primary`/`acct2`/`acct3`), not over a table of
   arbitrary users with arbitrary broker credentials. A second real user does not have a
   slot.
2. **Book isolation at scale.** §4 lists five occasions where per-book measurement was
   collapsed into global enforcement, most recently 2026-08-27. Every one of those was
   found by accident. With real users, the same class of defect is a cross-account
   information and capital leak, not just a nuisance.
3. **Admin routes.** `/api/admin/diagnose`, `manual-trade`, `scope-adjustments`,
   `settings-audit`, `settings-sync` — their authorization needs to be verified against a
   non-owner session, not assumed.
4. **The `/api/internal/broker-token` route** — anything named "internal" that is reachable
   over HTTP deserves an explicit auth check.
5. **Payments.** `agents/app/payments/` and `0036_payment_instructions` exist; whether
   there is a real billing path is unverified.
6. **Live trading.** There is none. `TRADING_MODE=live` is inert; the live executor was
   never built; `GO_LIVE_CHECKLIST.md` gates it. A user-facing product that implies real
   money is not close.
7. **The public surface.** There is no public deployment. The dashboard is a Tailscale-only
   service on Mike's server. `api.trezo.app` in
   `docs/workspace/TREZO_PROJECT/01_handoff_specs/TREZO_API_INTEGRATION.md` is
   aspirational — nothing is deployed there.

Treat "a running trading site for users" as a **program**, not a checklist item, and treat
§4's book-isolation rule as its primary safety requirement.

---

## 13. Document map — where the rest of the history lives

Everything below is already in the repo. This export is the index; those are the sources.

**Strategy specs (`docs/strategy/`)**

- `DIVIDEND_LT_PARAMETERIZED_SPEC.md` — the Dividends LT lane, §1–§7. Authoritative.
- `ENGINE_AUDIT_2026_08_22.md` — live vs dead module inventory; 5 dead modules removed in
  `61376b3`.
- `DATA_SOURCES_2026_08_23.md` — which feed supplies what, and its limits.
- `LADDER_REPLAY_2026_08_23.md` — ladder behaviour replayed against real data.

**Working history (`docs/workspace/`)**

- `TREZO_MEASUREMENT_PROGRAM_V2.md` (2026-08-29) — **current** measurement program, on
  Alpaca + Treasury rails. Supersedes the QC version in practice.
- `TREZO_QC_MEASUREMENT_PROGRAM.md` — the 9-experiment QuantConnect program (E1 delta +
  premium table, E2 assignment probability from finished-ITM, E3 wheel TR, E4 ladder
  yield/growth, E5 block cost, E6 risk-free sensitivity, E7 the §7 SPY/SGOV benchmark, E8
  open-interest floor, E9 trailing-vs-indicated yield mis-sort). E1 and E2 need no
  backtest.
- `TREZO_LANES_AUDIT_2026_08_20.md`, `TREZO_TRADE_DATA_REVIEW_2026_08_20.md`,
  `TREZO_KILLSWITCH_FREEZE_REPORT_2026_08_17.md`, `TREZO_VERIFICATION_REPORT.md`,
  `TREZO_REVIEW_RESPONSE.md` — prior audits and their answers.
- `TREZO_AGENT_PROPOSALS.md`, `TREZO_LIBRARY_PLAN.md`, `TREZO_PLAN_RESEARCH_DESIGN.md` —
  design direction.
- `TREZO_SITEMAP_AND_FLOW.md`, `TREZO_DESIGN_HANDOFF.md`, `TREZO_CONFIGURE_DESIGN.md`,
  `TREZO_user_flow.mermaid`, `TREZO_trading_logic.mermaid`, `TREZO_PLATFORM_MAP.pdf`,
  `TREZO_PLATFORM_MAP_philosophy.md` — product/design. *Note the sitemap still says 21
  agents; there are 30.*
- `GO_LIVE_CHECKLIST.md`, `DEFERRED_ITEMS_TRACKER.md`, `DATA_FEEDS_SETUP.md`.
- `reports/midday-snapshot-*.md` — ~40 daily operational snapshots, June–August 2026.
- `Neo-Obsidian Website Variations update` and `... update 2` — the dashboard design
  prototypes (Vite/shadcn) the current Next.js UI was derived from. Reference only, not
  built or deployed.

**Long-form project archive (`docs/workspace/TREZO_PROJECT/`)**

- `01_handoff_specs/` — the original specifications: `TREZO_ARCHITECTURE.md`,
  `TREZO_AGENT_SPEC.md`, `TREZO_STRATEGY_RULES.md`, `TREZO_NOVA_BOT_TRADE_RULES.md`,
  `TREZO_PATTERN_ENGINE.md`, `TREZO_CREDIT_SPREADS.md`, `TREZO_DAILY_PROFIT_LOCK.md`,
  `TREZO_DAY_TRADING_REFINEMENTS.md`, `TREZO_ETHICAL_FILTERS.md`,
  `TREZO_FOUNDER_WATCHLIST.md`, `TREZO_TAX_STRATEGIES.md`, `TREZO_WOVEN_BASKET.md`,
  `TREZO_PHASE_PLAN.md`, `TREZO_API_INTEGRATION.md` (aspirational endpoints — see §11).
- `02_restore_points/` — master and personal restore documents.
- `03_prototypes/` — the early Nova bot prototypes (JSX + Python) the platform grew from.
- `05_for_claude_code/checkpoints/` — **~70 phase-completion records**, `phase_0` through
  `phase_14` plus feature checkpoints. This is the build's chronological log; read it when
  you need to know *why* something was built the way it was.
- `06_external_research/` — five external QuantConnect strategies studied for ideas, plus
  `INSIGHTS.md`.

**Root-level**

- `PROJECT_STATUS.md` — *body still reads June in §2/§6; treat as stale.*
- `TREZO_TRADING_PHILOSOPHY.md`, `PAGE_PATTERN.md`, `TEST_CHECKLIST.md`, `SETUP.md`,
  `REBUILD-SERVER.md`, `README.md`.
- `agents/app/paper/CAPITAL_ALLOCATION.md` — how capital splits across pockets/lanes.
- `Trezo-Complete-Development-Record.xlsx`, `Trezo-Work-Log.xlsx` — the work log.

**Outside the repo, on the laptop**

- `C:\Trezo\reports\incident-2026-08-31-approval-outage.md` — the full four-day-outage
  write-up (§6).
- `C:\Trezo\` root — deploy/backup PowerShell (`AUTO-PUSH.ps1`, `AUTO-PULL.ps1`,
  `BACKUP-USB.ps1`, `SETUP-GITHUB-DEPLOY.ps1`, `VERIFY-LAPTOP.ps1`, `PRE-SALE-CHECK.ps1`),
  server notes (`SERVER-SETUP.txt`, `SERVER-PASTE.txt`, `DEPLOY-OVER-RDP.txt`),
  `REBUILD-FROM-USB.md`, and `Quantconnect/`.

---

## 14. How Mike wants to be worked with

- Call him **Mike**. Be concise and direct; minimal formatting; prose in chat rather than
  report-style headers and bullets unless he asks.
- Lean output. Do not generate Word/PowerPoint/Excel/PDF files unless he clearly asks or
  it is a formal deliverable. If unsure, offer rather than auto-create.
- Scale effort to the task. Go deep when it is warranted, not by default.
- **Surface decisions, do not make them.** The HELD FOR MIKE list in §10 is his to resolve.
  Behaviour changes to the kill-switch knobs, the R:R floor, lane modes, or the recovery
  policy need his sign-off.
- He values being told when something does not bind, more than being told something shipped.
  "Shipped and verified in the live log" is the standard; "shipped" alone is not.
