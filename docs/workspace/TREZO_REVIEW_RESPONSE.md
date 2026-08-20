# Trezo — Response to Technical Review

*2026-08-10. Every claim in your list was tested against the live system before
this reply — two of your items turned out stronger than written, one needs a
level set from data that item 1 will produce, and one has a side effect worth
deciding on deliberately. Nothing has been changed yet.*

---

## 1. What verification found

**Item 1 (per-lane accounting) — accepted, and cheaper than you think.**
All 212 closed trades already carry a lane tag; this is a reporting change, not
instrumentation. Running your five columns immediately:

| lane | n | mean $ | stdev | 95% CI | verdict |
|---|---|---|---|---|---|
| extended | 48 | +2.48 | 17.38 | [−2.43, +7.40] | CI contains zero |
| default | 30 | −0.43 | 22.65 | [−8.53, +7.68] | CI contains zero |
| forex_swing | 28 | +0.19 | 0.68 | [−0.06, +0.44] | CI contains zero |
| crypto_scalp | 26 | −3.34 | 9.70 | [−7.07, +0.39] | CI contains zero |
| stms | 24 | −0.36 | 1.93 | [−1.13, +0.41] | CI contains zero |
| **crypto_dca** | **19** | **−5.80** | **9.22** | **[−9.95, −1.66]** | **NEGATIVE** |
| pattern | 14 | −10.38 | 26.68 | [−24.36, +3.59] | CI contains zero |
| reconciled | 14 | +1.30 | 21.13 | [−9.77, +12.37] | CI contains zero |
| crypto_swing | 7 | −19.33 | 48.43 | [−55.21, +16.55] | CI contains zero |

You were right that the pooled −$2.03 described nothing. The corrected picture:
**one lane is provably losing (crypto_dca); every other lane is unmeasured, not
bad.** That is a far more actionable statement — one lane to fix or cut, the
rest need sample size, and "the edge is negative" was an aggregation error.

**Item 4 (variance-premium veto) — accepted; your safety margin verified; one
side effect flagged.** Measured across two full days: 89% of readings are CHEAP,
but that still leaves **~200 RICH candidates per day**, and at the current
1-CSP cap the Wheel needs one. The veto cannot starve the lane.

The side effect: RICH names are high-IV names (live examples: implied 55% vs
realized 31%; implied 140% vs 115%). A only-write-when-rich rule therefore
**selects for volatile underlyings**, while the Wheel bench (O, MAIN, ARCC,
STAG, T, KO-type names) was picked for income stability. The filter is
vol-seeking; the bench is income-seeking. We will still do it — but the bench
composition should be revisited at the same time, or the Wheel will drift toward
names it wasn't designed to hold. If you have a preferred way to reconcile
those two pressures, that's a question we'd value an answer on.

**Item 5 (hard diversification floor) — accepted in principle; the LEVEL must
come from item 1's data.** Your arithmetic is right: at 64% concentration, a
4.7% factor move trips the 3% kill-switch. But crypto was **94% of approvals**
on the day measured. A floor set naively at today's concentration would not
rebalance the book — it would approximate a halt, which contradicts your own
(correct) argument under "don't wire optimal-f as a veto: you need trade flow
to learn anything." Agreed resolution: build the floor now, constrain on the
diversification ratio as you specify, but set the initial level from the
per-lane report so it forces rotation rather than a stop, and log every refusal
it would have made for a week before it goes hard.

**Items 2, 6, 8 — accepted without qualification.** One implementation note on
item 2: invalidating flat-slippage history also invalidates what the learning
loop's outcome-weighted selection was trained on. The invalidation flag will
propagate there too — otherwise the selector keeps acting on fills the new
model says were fiction.

**Item 3 (config freeze) — accepted as code; flagging the real cost.** The hash
and window mechanics are simple. The cost is operational: a valid window means
**no strategy changes for its duration**, and this platform has shipped changes
almost daily. The discipline is the feature. Window length will follow from
item 1's per-lane n (at current throughput, most lanes need weeks, not days, to
move a CI off zero) — so the freeze calendar is a consequence of the statistics,
not a preference.

**Item 7 (resource conflict) — accepted, and it goes first.** One verified fact
you didn't have makes it stronger: posture is chosen by equity, and the
threshold sits exactly at $25,000 — so the 25k book already qualifies as
**balanced**: 2 concurrent CSPs, 35-DTE cap, 40% collateral (a $10,000 wheel
allowance), and a $5,000 options pocket. Moving the Wheel there doesn't just
free the primary's cash — it doubles the Wheel's slots and widens its bench
beyond the Tier-D names the primary could afford. The primary keeps its fast
lanes with its cash unlocked.

**Your deferrals — all accepted.** On rolls, your argument (slot throughput
beats roll retention at a 1-CSP cap) is better than the one that put rolls on
the gap list. On not adding lanes: the per-lane table above makes your case
numerically — seven lanes averaging n≈28 is why nothing is measurable. On the
contribution schedule: correct that it's the largest lever on the list; it's a
budgeting decision and it's being treated as one.

---

## 2. Agreed sequence

| order | item | size | why this position |
|---|---|---|---|
| 1 | **7** — move Wheel to 25k book | config only | unblocks two lanes today; no code |
| 2 | **1** — per-lane report | small | everything downstream needs its numbers |
| 3 | **8** — two regression tests | small | locks the two worst past defects out |
| 4 | **6** — cost gate on all lanes | medium | extends a pattern that already works |
| 5 | **2** — size-aware slippage | medium | required before any scaling claim |
| 6 | **4** — variance-premium veto | small | after the bench decision from §1 |
| 7 | **5** — diversification floor | medium | level set from item 1's data |
| 8 | **3** — config freeze | small code, large discipline | starts the first clean window |

Not before item 2 ships: any conclusion from the 25k/75k books beyond "the
plumbing works."

---

## 3. How the budget changes across portfolio sizes

Requested addition. All numbers from the live allocation and posture code, not
projections. Posture is automatic from equity: **<$25k growth · $25k–$100k
balanced · ≥$100k income** (overridable per account in settings).

**Allocation pockets (what each lane may deploy)**

| pocket | $4.7k growth | $25k balanced | $75k balanced | $100k income |
|---|---|---|---|---|
| stocks | 42% · $2,001 | 32% · $8,000 | 32% · $24,000 | 18% · $18,000 |
| crypto | 32% · $1,525 | 18% · $4,500 | 18% · $13,500 | 9% · $9,000 |
| options | 10% · $477 | 20% · $5,000 | 20% · $15,000 | 20% · $20,000 |
| income | 10% · $477 | 25% · $6,250 | 25% · $18,750 | 48% · $48,000 |
| forex | 6% · $286 | 5% · $1,250 | 5% · $3,750 | 5% · $5,000 |

The design intent is visible in the drift: growth accounts lean into the
volatile lanes; income accounts progressively hand capital to the dividend and
option-income layers.

**Wheel capacity**

| | $4.7k | $25k | $75k | $100k |
|---|---|---|---|---|
| posture | growth | balanced | balanced | income |
| collateral cap | 25% · $1,191 | 40% · $10,000 | 40% · $30,000 | 50% · $50,000 |
| concurrent CSPs | 1 | 2 | 2 | 3 |
| max DTE | 21 | 35 | 35 | 45 |
| $10-strike CSPs it could carry | 1 | 10 | 30 | 50 |

**Risk and safety rails (current per-book settings)**

| | primary $4.7k | 25k book | 75k book |
|---|---|---|---|
| risk/trade | 4% · ~$190 | 4% · $1,000 | 10% · $7,500 |
| max open | 14 | 14 | 6 |
| total at risk deployed | ~56% | ~56% | ~60% |
| kill-switch (3% day) | ~$143 | $750 | $2,250 |
| daily goal rung | $50 "grind" | $293 | $480+ ladder |

The 75k book is a deliberate experiment: same total exposure as the others,
concentrated into six bets instead of fourteen — testing whether bet size, the
one variable that differs, changes the outcome. Per your item 2, its results
are unmeasured until slippage is size-aware.

---

## 4. Questions back

1. The variance filter selects volatile names; the bench selects stable payers.
   Reconcile by widening the bench, by a per-name IV-rank threshold instead of
   an absolute CHEAP/RICH cut, or by something else?
2. For the diversification floor: given one lane provably negative and the rest
   unmeasured, would you set the initial ratio from the current book (grandfather
   it) or from a target book (force rotation immediately)?
3. Minimum n per lane before you'd treat a CI verdict as real rather than noise
   — 30? 50? The freeze calendar hangs on this.

*— Mike (with Nova, the platform's engineering agent)*
