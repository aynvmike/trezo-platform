# Strategy Spec — "Dividends (Long-Term)", Parameterized
### Capital-agnostic addendum to DIVIDEND_LT_STRATEGY.md
*2026-08-13. For the platform's engineering agent. Every figure traces to the 24-fund capture
study, the verified Webull ledger, or the long-record funds checked live (SCHD, QYLD).
Anything not measured is labeled UNPROVEN. Paper only; mode switches and any real-money
decision are the owner's.*

---

## 0. What changed from the original spec

The original spec hardcoded a $75k book and a $36k sleeve. That was wrong — sizes are inputs,
not architecture. This document replaces every fixed dollar figure with a parameter, adds the
graduation state machine, and defines one new UI object: **the target-return readout**, which
displays what a return target would require instead of pursuing it.

The design invariant that motivates all of it, from the owner's own book:

> Six positions, one wrapper class, one era. Cash yield on cost was **17.6%, near-uniform
> across all six**. Total return ranged **−17.0% to +22.6%** — a 16-point standard deviation.
> Three of six cleared +12% (AMZY +22.6%, NVDY +14.4%, GOOY +12.4%).
>
> **12% is not the hard part. Reaching it on purpose is.** The payout carried no information
> about the outcome. This sleeve's job is not a higher mean — it is a narrower spread.

---

## 1. Inputs — what the owner controls

| # | parameter | type | range / guardrail | default |
|---|---|---|---|---|
| 1 | `capital` | manual entry, any amount | ≥ $500; no upper bound | — |
| 2 | `contribution_monthly` | manual entry | ≥ 0 | 0 |
| 3 | `w_ladder` | slider | 50–90% | 70% |
| 4 | `w_wheel` | slider | 0–40% | 25% |
| 5 | `w_buffer` | slider | 3–20% | 5% |
| 6 | `mode` | ACCUMULATE / INCOME / PARTIAL(x%) | — | ACCUMULATE |
| 7 | `wheel_delta` | slider | **0.15 – 0.40, hard-capped** | 0.25 |
| 8 | `target_return` | slider | 5–25% | **display-only — see §5** |

Weights normalize to 100% on any change (adjust the largest non-touched weight). Guardrails
are hard: `w_wheel > 40%` is not an aggression setting, it is a different strategy, and the
lane must refuse rather than silently become one.

`wheel_delta` is the ONLY input that changes expected return. That is deliberate — one risk
knob, bounded, labeled, logged in the config hash.

## 2. Derived sizing — pure functions of the inputs

```
L = capital * w_ladder        W = capital * w_wheel        B = capital * w_buffer
ladder_names  = clamp(floor(L / 1000), 1, 15)
csp_blocks    = floor(W / block_cost)          # block_cost = 100 * cheapest bench price
income_monthly = L*0.053/12 + csp_blocks*block_cost*prem_rate + B*0.0375/12
expected_TR    = w_ladder*(0.053+0.045) + w_wheel*0.080 + w_buffer*0.0375
```

Calibration constants (each replaced by measurement as the lane accrues data):
`ladder_yield 5.3%` (blended screened bench) · `ladder_growth 4.5%` (SCHD-class realized
payout growth ~11%/yr, price ~10%/yr over 15 yrs; discounted hard) · `wheel_TR 8.0%`
(net of assignment give-back; BXM's 40-yr record says the *net* add over buy-and-hold is
low single digits — UNPROVEN in this lane until measured) · `buffer 3.75%` ·
`prem_rate 0.60%/mo` at delta 0.25.

**Scaling reference** (defaults 70/25/5, block_cost $3,500):

| capital | ladder names | CSP blocks | income/mo | expected TR |
|---|---|---|---|---|
| $2,000 | 1 | 0 | $6 | 9.0% |
| $5,000 | 3 | 0 | $16 | 9.0% |
| $10,000 | 7 | 0 | $32 | 9.0% |
| $20,000 | 14 | 1 | $86 | 9.0% |
| $35,000 | 15 | 2 | $156 | 9.0% |
| $50,000 | 15 | 3 | $225 | 9.0% |
| $75,000 | 15 | 5 | $349 | 9.0% |
| $100,000 | 15 | 7 | $472 | 9.0% |
| $250,000 | 15 | 17 | $1,169 | 9.0% |

Expected TR is flat across capital — correct and important. **Size buys mechanics, not edge.**
Anything in the UI implying bigger = better-returning is a bug.

## 3. The graduation state machine

Positions and the book both graduate. Nothing is capital-specific; thresholds simply fire at
different capital levels.

**Per-name states** — a name is always in exactly one:

```
FRACTIONAL   shares < 100                    → dividends only, no options
LOT_READY    shares ≥ 100, tier = HIGH_YIELD → covered calls eligible
LOT_HELD     shares ≥ 100, tier = GROWTH     → NEVER write calls (see §4)
CASH_SECURED cash reserved for a CSP         → premium, no dividend
ASSIGNED     CSP exercised, shares held      → dividends + CC eligible
```

`FRACTIONAL → LOT_READY` fires when a position organically reaches 100 shares. Compounding
unlocks option income name by name; the platform must log the transition as a lane event.

**Book-level unlocks:**

| gate | condition | effect |
|---|---|---|
| U1 wheel | `W ≥ block_cost` | CSP engine enabled |
| U2 multi-CSP | `csp_blocks ≥ 2` | concurrency cap = `csp_blocks` |
| U3 diversification | `ladder_names ≥ 12` | per-name cap relaxes 20% → 10% |
| U4 selectivity | `capital ≥ $50k` | per-name IV-rank filter + sector caps bind |

Below U3, the concentration cap is the binding risk control and must be enforced, not warned.

## 4. Lane rules — the five that make ladder + wheel share one lane

Derived last session; each is a build item, not a guideline.

1. **Two-state names.** Every wheel name is either cash securing a put or shares wearing a
   call. The lane earns in both states. Sequential, never simultaneous.
2. **Graduation at 100 shares.** Round lots gate covered calls; fractional ladder positions
   are dividend-only until they graduate.
3. **Ex-date guard.** Never carry an ITM short call into an ex-date. An ITM call whose
   remaining time value is below the dividend gets exercised early and takes the dividend
   with it. Rule: expiration clears the ex-date, or maintain an OTM buffer.
4. **No covered calls on GROWTH-tier names.** Writing calls on the compounders sells the
   4–6%/yr payout growth that justified owning them — the capture-asymmetry mistake from the
   YieldMax study, rebuilt by hand. HIGH_YIELD tier wheels freely; GROWTH tier never.
5. **Hard collateral reservation.** CSP collateral is reserved cash and cannot double-count as
   ladder capital. Same defect family as the primary book's options-BP accounting bug — ship
   the reservation before the first CSP.

**Entry screen (unchanged, applies to every name):** payout ratio ≤ 70% of earnings or FCF
(coverage ratio for REITs/BDCs) · dividend-raise streak ≥ 10 yrs, ≥ 25 preferred · no cut in
trailing 10 yrs · ≤ 2 names per sector, REIT/BDC = one factor · for any fund: AUM ≥ $100M, no
reverse split in 24 months, trailing payout ≤ trailing total return.

**Asset-location tags** (free now, a migration later): `taxable_bucket` for qualified growers,
`roth_bucket` for wheel premium and REIT/BDC ordinary income. Paper ignores tax; the tag
carries the architecture forward if the lane graduates to real money.

## 5. The target-return readout — the one novel object

`target_return` is a slider, but it is wired to **explain**, not to **actuate**. Moving it
changes no order, no strike, no allocation. It prints the requirement:

```
gap                   = target_return − expected_TR
appreciation_required = 0.045 + gap / w_ladder      # the market-outcome path
premium_required      = 0.0060 + gap / w_wheel / 12 # the setting path
```

At defaults (baseline 9.05%):

| target | gap | needs ladder appreciation of | …or monthly wheel premium of |
|---|---|---|---|
| 9% | −0.1% | 4.4%/yr | 0.58%/mo |
| 10% | +1.0% | 5.9%/yr | 0.92%/mo |
| **12%** | **+3.0%** | **8.7%/yr** | **1.58%/mo** |
| 15% | +6.0% | 13.0%/yr | 2.58%/mo |
| 18% | +9.0% | 17.3%/yr | 3.58%/mo |
| 20% | +11.0% | 20.1%/yr | 4.25%/mo |

**The two paths are not equivalent, and the UI must say so.** Appreciation is a market outcome
you wait for — dividend growers deliver 8.7% in plenty of years, at no added risk. Premium is
a setting you choose — 1.58%/mo means writing far closer to the money, capping most upside,
and constant assignment. Same number, two different animals: one is patience, one is leverage
on conviction.

Copy requirement: when `premium_required` implies delta > 0.40, the readout reads
**"unreachable within lane guardrails"** and names which rule blocks it. No silent extrapolation.

Delta reference for the readout (UNPROVEN pending live chain data — replace with measured):

| delta | ~premium/mo | blended TR | assignment prob/expiry |
|---|---|---|---|
| 0.15 | 0.40% | 8.4% | ~15% |
| 0.20 | 0.52% | 8.8% | ~20% |
| **0.25** | **0.60%** | **9.0%** | **~25%** |
| 0.30 | 0.75% | 9.5% | ~30% |
| 0.40 | 1.05% | 10.5% | ~40% |

Note what the last column costs: at delta 0.40 the lane is assigned ~40% of expirations, which
turns the ladder over constantly — churning the very positions whose dividend growth is the
strategy. The premium path buys return by selling the compounding.

## 6. What the lane honestly produces

ACCUMULATE, no contributions, five years:

| | at 9% | at 12% |
|---|---|---|
| $20,000 | $30,772 | $35,247 |
| $50,000 | $76,931 | $88,117 |

With $300/mo added: $20k → **$53,192 / $59,349**; $50k → **$99,351 / $112,219**. The
contribution row dwarfing the return row held in every projection run this cycle — that is the
finding, not a footnote. In a normal-to-good market this design prints 12–14% with the delta
slider untouched; the ceiling was never the constraint.

INCOME mode is unchanged: monthly draw = `min(actual distributions, 90% of trailing-12mo total
return)`, shortfalls from the buffer, excess auto-reinvests.

## 7. Measurement and rails

Judged on **forecast MAPE** (weekly), **recycling ratio ≤ 1.0** (monthly, per holding),
**TR vs 50% SPY / 50% SGOV** (monthly), **forward income per $1k** (quarterly). Per-trade CIs
don't apply to a book that trades 2–6×/month; freeze windows are calendar-based (quarterly).

Rails: kill-switch baseline must be total-return aware (ex-div NAV drops are not losses —
sibling of the $4.52 halt defect) · **test-zero: verify Alpaca paper credits dividends at all**
before the first ex-date; if it doesn't, synthesize credits tagged `simulated_cashflow`, flagged
like forex_swing, never hidden · config hash on every order · exits: recycling ratio > 1 for two
quarters → rotate; dividend cut → immediate review; payout ratio breach → review.

90 days proves plumbing and forecast accuracy. 12 months is the minimum for a TR verdict. That
gate does not move, and no dial in §1 moves it.

*— Nova (Cowork side), for Mike and the platform's engineering agent*
