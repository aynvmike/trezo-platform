# Trezo Capital Allocation — the Sleeve System

*The "language" the agents use to decide how much money goes where, and for how long.*
Part 1 shipped 2026-06-17. Owner: Mike. Code: `agents/app/paper/sleeves.py`.

## The problem this fixes

The old setup had **one shared pool**, a single cap of **3 open positions total**,
and sized each trade at up to **25% of the account** — with capital split only by
asset class (crypto / stocks / options / income). Whatever scanner fired first
grabbed the open slots, which was almost always the fast stock day-trade scanners.
So a couple of stock names ate the buying power and the Wheel, crypto, options and
dividend layers never got funded. That is the "stuck in 3 names, two of them the
same strategy, $0 buying power" situation.

The fix is a **capital-sleeve layer**: each trading *horizon* gets its own reserved
budget that the others cannot eat, plus caps that stop the same strategy being
stacked across names. The layer system finally has teeth at the capital level.

## The three sleeves

| Sleeve | Horizon | Layers it funds | Profit rule |
|---|---|---|---|
| **Active** | Intraday → next-day | 2 Stock intraday (STMS/ORB/pattern), 1 Crypto short (scalp/swing), 4 Stock weekly | Quick profit-based exits; ride the ladder stops |
| **Quick Options** | 2–3 days | 3 Options engine (directional calls / spreads) | **Take +30% and recycle into the options sleeve** |
| **Holding** | Days → indefinite | 5 Wheel, 6 Dividends, 1 Crypto hold (HODL/DCA), 7 Quality cores | Lock with ladders, collect premium, let dividends compound |

Your "$3k for daily" = **Active + Quick Options** together. Your "$2k for longer" = **Holding**.
KINDRIP (child accounts) is funded separately and is not one of these trading sleeves.

## How the split is set — it rides your risk dial

The split is a **percentage of equity**, driven by the account risk profile, so it
scales as the account grows. It is not a fixed dollar amount.

| Profile | Active | Quick Options | Holding | On $5,000 |
|---|---|---|---|---|
| Conservative | 25% | 10% | 65% | $1,250 / $500 / $3,250 |
| **Balanced** | **40%** | **20%** | **40%** | **$2,000 / $1,000 / $2,000** |
| Aggressive | 50% | 25% | 25% | $2,500 / $1,250 / $1,250 |

**Balanced reproduces exactly the $2k / $1k / $2k you described.** Expert users can
override any sleeve's dollar budget directly.

## The rules that stop capital getting stuck

Each sleeve carries its own caps (defaults, all tunable):

| Sleeve | Max open | Max per strategy | Max per ticker |
|---|---|---|---|
| Active | 3 | 2 | 1 |
| Quick Options | 4 | 3 | 1 |
| Holding | 6 | 3 | 2 |

- **Reserved budget** — the Active sleeve physically cannot spend the Holding or
  Options money, so the slower layers are always funded.
- **Max per strategy** — this is the direct fix for "two of the same strategy." The
  Active sleeve will not open a 3rd ORB (or 3rd of anything) at once unless it is proven.
- **Max per ticker** — stops three different strategies all piling onto one name.

## Soft budgets, with a proven-trade override

Budgets are **soft, not a hard wall** — your call. When a sleeve is over budget the
agents normally **hold the trade and log a warning** (so capital does not over-pile),
**except** when the strategy's *real, logged* track record clears the proven bar:

- **Win-rate ≥ 75%** (tunable: `PROVEN_WIN_RATE`)
- over **≥ 10 closed trades** (tunable: `MIN_PROVEN_TRADES`) — so a hot streak of 2–3
  trades cannot "prove" anything
- and even a proven trade may only push the sleeve to **1.5× its budget** (`MAX_BREACH_MULT`),
  never further — so one strategy can't quietly swallow the whole account.

Worked example — your ORB case, Active sleeve at $2,000 budget, $1,950 already deployed:

| ORB's logged record | Decision |
|---|---|
| 78% over 12 trades | **override_proven** → trade allowed (the high-probability ORB gets through) |
| 60% over 12 trades | **hold_over_budget** → skipped + warned (not proven enough) |
| 90% over only 3 trades | **hold_over_budget** → skipped (too few trades to trust) |

The win-rate and trade count come straight from your learning loop
(`strategy_weighting.get_live_strategy_edge`), so this gets smarter as more trades close.

## Strategy → sleeve map

- **Active:** stms, orb, pattern, extended (swing), crypto_scalp, crypto_swing
- **Quick Options:** long_call, long_put, bull_call_spread, bull_put_spread, iron_condor, cash_secured_put (standalone), iv_crush_short
- **Holding:** wheel_csp, wheel_cc, dividend_capture_long, yieldmax, crypto_hodl, crypto_dca, quality cores

*One judgment call:* `extended` (2–7 day stock swing) currently lives in **Active** as an
actively-managed directional trade. Easy to move it to Holding if you'd rather it count
as a longer hold — one line.

## What's live now vs. coming next

- **Part 1 (done):** the policy + math + this spec. Nothing in the live trade path
  changed yet — the sleeve plan and decisions are defined and self-tested.
- **Part 2:** wire the soft budget gate + proven override + caps into the Trade
  Execution and Risk Manager path (this is what changes behavior).
- **Part 3:** per-sleeve hold-window + profit-take templates (incl. the 30% options recycle).
- **Part 4:** a dashboard panel showing each sleeve's budget / deployed / free.
- **Part 5 (later):** forex sleeve, once a forex engine exists.

## Capital velocity & account scaling (Part 2 update, 2026-06-17)

The sharper principle behind the sleeves: **capital velocity**. A dollar that
turns over several times a day is worth more than one locked for weeks, so the
engine rewards fast recycling and lets the account's size set how much it runs.

**Velocity sets the per-trade bite.** Each strategy has a turnaround tier, and
the bite it may take from its sleeve scales with that tier:

| Turnaround | Strategies | Bite (of sleeve) |
|---|---|---|
| Fast (minutes–hours) | crypto scalp, ORB | 30% |
| Intraday / short (hours–few days) | STMS, pattern, crypto swing, options, extended | 20% |
| Long (weeks–indefinite) | wheel, dividends, crypto HODL/DCA | 10% |

On a balanced $5k account (Active sleeve $2,000): a fast ORB may take ~$600
because it's back the same day and redeploys, while a locked wheel/HODL trade
takes ~$200. The same sleeve throws off many quick trades instead of sitting in
one name for weeks.

**Capacity scales with the balance.** Position capacity isn't a fixed number —
it grows with equity (`scaled_max_open` ≈ equity / $500, clamped 4–40) and with
each sleeve's budget. Bigger account → more of the market worked at once.

| Account | Up to ~positions |
|---|---|
| $1,000 | 4 |
| $5,000 | 10 |
| $25,000 | 40 |

**Priority = edge × velocity.** When slots are contended, quick + proven setups
fire first. (Wiring in Part 2b.)

**Status (2026-06-17):** Part 1 (policy) + Part 2a (budget gate + proven
override + velocity bite, live in trade_execution) are in. Part 2b wires the
scaled cap + priority into the Risk Manager (replacing the static
`max_open_positions=3` bottleneck) and adds the count caps. Part 2c widens the
fast scanners to the market-wide pool. Part 3 = hold/profit templates. All
numbers above are tunable.
