# Dividend ladder — 3-month replay
### 2026-05-23 → 2026-08-22. Run against the shipped modules, not a reimplementation.

Mike asked what the ladder would have produced over the past three months.
The honest headline: **it beat every benchmark, and that is not yet
evidence of anything.** The exercise earned its keep for a different
reason — it found a defect that would have made the lane do nothing at
all.

---

## 0. The finding that mattered

The screen shipped that morning **admitted zero names.** Not "few" —
zero. Every ticker returned `passed=False, tier=UNVERIFIED`.

Cause: the §4 entry screen needs a dividend-raise streak and a cut
history, both of which require the dividend PAYMENT SERIES. Finnhub's
`/stock/dividend` is not on this account's tier — it answers *"you don't
have access to this resource."* The module correctly marked those checks
UNVERIFIED and correctly refused to pass a name on unverified evidence.
Both halves right; the combination fatal. The Wheel's market-wide path
would have gone silent and the ladder agent would have proposed nothing,
and — this is the part worth sitting with — **it would have looked like
a strict gate doing its job.** No errors, no alerts, just an empty
universe.

A gate that blocks everything is not strict. It is broken.

### The fix, and the second defect inside it

`dividendGrowthRate5Y` IS available, so it now stands in for the streak
— but the raw number **inverts the rule it proxies**:

| name | 5Y dividend growth | what it actually means |
|---|---|---|
| TMUS | **+123.7%** | initiated a dividend recently — CAGR off ~zero |
| F | **+38.1%** | cut to zero in 2020, reinstated — recovery, not a streak |
| MAIN | +11.7% | a real raiser |
| JNJ | +7.7% | a real raiser |

In the first run the ranking dutifully put **TMUS and Ford at the very
top of the ladder** — the two names §4's "no cut in trailing 10 years"
exists specifically to exclude. Ford's trailing dividend was also *below*
its annual rate: shrinking right now, ranked second.

Two guards now: growth above 25%/yr is read as a reinstatement artifact
rather than excellence, and trailing-vs-annual catches a payout shrinking
today even when the 5Y average is positive. Both fire on exactly the
names above.

---

## 1. What the screen rejected

Of 75 names scanned, 24 passed. The rejections are the product:

```
T       5Y dividend growth -11.2% — shrinking, not raised
NLY     5Y dividend growth -6.8%  — shrinking, not raised
KHC     payout 70% at ceiling AND shrinking
F       reinstatement artifact + trailing below annual
TMUS    reinstatement artifact (+124%)
ABBV    payout ratio 276% over the 70% ceiling
DOW     payout ratio 176%
CVX     payout ratio 104%
MO      payout ratio 100%
INTC    yield 1.14% below the 1.5% floor
```

Realty Income (O) shows a 276% *earnings* payout ratio and still passes —
correctly. It is a REIT, judged on coverage, and the module's
`CASHFLOW_PAYERS` branch is what keeps the screen from throwing out an
entire asset class over the wrong denominator.

**Dividend ETFs (SCHD, VYM, DGRO, HDV, DVY) come back UNVERIFIED** —
Finnhub's metric endpoint does not cover funds. They are excluded rather
than assumed good. That is a real coverage gap, not a passing detail.

---

## 2. The result

Equal weight, dividend-adjusted total return (Alpaca `adjustment=all`, so
distributions are in the price series rather than reconstructed).

| | ladder | 3-month TR |
|---|---|---|
| 25k book (income pocket $7,500) | 5 names | **+11.93%** |
| 75k book (income pocket $20,000) | 14 names | **+12.07%** |
| SPY | | +2.28% |
| SCHD (dividend ETF) | | +8.33% |
| SGOV (cash) | | +0.89% |
| **50% SPY / 50% SGOV** — the spec's benchmark | | **+1.59%** |

The two books landing 0.14pp apart is the design working: same screen,
same ranking, different capital, near-identical outcome. *Before* the
artifact fix they were **6.75 points apart** (+2.29% vs +9.04%) because
the 5-name book was drawing entirely from the poisoned top of the
ranking. Size bought mechanics, not edge — exactly as §2 promises.

---

## 3. Three reasons not to believe it yet

**The spread is wide, and the spread is the whole objective.** The spec's
invariant is *"not a higher mean — a narrower spread."* This delivered:

| set | n | mean | **stdev** | best | worst |
|---|---|---|---|---|---|
| top-5 | 5 | +11.93% | 9.04pp | +23% | −3% |
| top-14 | 14 | +12.07% | **19.25pp** | +46% | **−35%** |
| all passing | 24 | +11.37% | 15.83pp | +46% | −35% |

An 81-point range between best and worst is not a narrow spread. QCOM
alone lost 35%. At 14 names one factor still dominates the book, which is
precisely why the crowding penalty exists.

**The ranking is not earning its place.** Ranked top-14 returned +12.07%;
simply holding *everything that passed* returned +11.37%. A 0.70pp edge
across 14 names over one quarter is indistinguishable from noise. The
SCREEN is doing the work; the ORDERING is not — at least not yet.

**Two names are half the result.** MPC (+46%) and AMGN (+32%) contribute
46% of the total. Remove them and the ladder returns **+7.63%** — which
is SCHD's +8.33%, slightly worse, for considerably more machinery.

---

## 4. The caveat that outweighs the rest

**Lookahead bias in the selection.** Names were screened on *today's*
fundamentals and then "held" for a window that has already happened. Any
company that cut its dividend during those three months now fails the
screen — so the simulation never bought the very names that would have
hurt it. This flatters the result and cannot be removed without
point-in-time fundamentals, which we do not have.

Also absent: **no wheel premium.** The 25% wheel sleeve needs historical
option chains we cannot get, and modeling it would be inventing the
number the exercise is meant to measure. This is the ladder alone.

Three months is one regime. The spec is explicit that 90 days proves
plumbing and **12 months is the minimum for a total-return verdict**, and
nothing here moves that gate.

---

## 5. What to do with it

1. **Ship the screen fix.** It is not optional — without it the lane
   admits nothing. Done.
2. **Find a fund data source.** Five dividend ETFs sitting permanently
   UNVERIFIED is a real hole, and they are the natural core of a ladder
   at small capital.
3. **Leave the ranking alone for now, but stop trusting it.** It adds
   0.70pp on this sample. Judge it on realized data at the 90-day mark,
   not on this.
4. **Watch the dispersion, not the mean.** If the 12-month number lands
   at +12% with a 19-point spread, the lane has not done its job. The
   thing worth measuring is whether that stdev comes down.

*— Nova, for Mike. Run against commits 41e5499 / 8de6677 with the
2026-08-23 screen patch.*
