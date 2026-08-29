# Trezo × QuantConnect — Measurement Program

**Handoff brief. Written for an agent with no prior context.**

Author: Nova (Claude Opus 5, Cowork session) · For: Mike · Date: 2026-08-29
Status: ready to execute · Estimated effort: E1–E3 in one session, the rest incremental

---

## 0. Mission, and the constraints that define it

You are being handed a **measurement program**, not a build. The deliverable is a set of numbers and a written report. Nothing else.

### The four hard constraints

1. **Do not modify Trezo.** Not one line, not one file, not a suggestion framed as a patch. Trezo is Mike's live algorithmic trading platform. It is out of scope, you will not be given access to it, and you should not ask. Every number you produce gets handed back as a *value with evidence*; Mike decides what happens to it.

2. **QuantConnect is a lab, not a platform.** Nothing migrates. No strategy gets ported. No order is ever placed through QuantConnect. You are running experiments in someone else's environment because it has data and modelling Trezo doesn't, and you are carrying conclusions home.

3. **Derived measurements out, raw data never.** QuantConnect's CLI data agreement states: *"Data is provided in LEAN format, cannot be manipulated for transmission or use in other applications."* Their download licence adds internal-LEAN-use-only, no redistribution, no conversion. The explicit carve-out is that you may share derived work *"if the original data can't be reconstructed."* So: a measured constant, a distribution, a bucketed table, a chart — fine. A dump of bars, quotes, or a chain — never. If an experiment's output starts to look like a reconstruction of their dataset, stop and say so.

4. **UNVERIFIED beats a guess.** This is Trezo's own house rule and it carries into this program: a bucket with too few observations reports `UNVERIFIED`, never an interpolated value. A number you are not confident in is worse than no number, because the whole point of this exercise is that Trezo is currently running on confident-looking placeholders. Do not replace one fiction with another.

### Why this program exists

Trezo is not short of data — it pulls live option chains from Alpaca on every trade attempt. It is short of **evidence**. Roughly a dozen constants that drive live position sizing are hardcoded placeholders, several of which say so in their own source comments. This program measures them.

---

## 1. Context: what Trezo is, in one page

Read this so you understand what each number is *for*. You do not need to see the code.

**The platform.** A Python agent engine (~30 registered agents on an async scheduler), a Next.js web UI, Supabase for storage, and Alpaca as the broker. It runs 24/7 on a Windows VM. It trades **three paper books** — a ~$5k primary, a $25k, and a $75k — all live and authenticating at Alpaca paper.

**The lanes that matter here:**

- **The Wheel.** Sells cash-secured puts, takes assignment, then writes covered calls against the shares. Lives inside a single ~2,900-line agent.
- **The Dividend Long-Term lane.** Buys a ladder of screened dividend payers and wheels the high-yield ones. Split by weights: `w_ladder` (default 70%), `w_wheel` (25%), `w_buffer` (5%).

**The design invariant of the dividend lane, in Mike's own words, from his own trading record:** six positions, one wrapper class, cash yield 17.6% near-uniform, total return −17.0% to +22.6%. *The payout carried no information about the outcome.* Therefore: **the lane's job is a narrower spread, not a higher mean.** Never propose "improving" it by raising expected return — that is the specific mistake it exists to correct. When you report a measurement, report dispersion as prominently as central tendency.

**Two facts about the Wheel you need, because they shape the first experiment:**

- The Wheel places strikes at a **fixed 5% out-of-the-money** (`CSP_OTM = 0.05`, `CC_OTM = 0.05`) at a **30-day target DTE** (`TARGET_DTE = 30`), and its contract picker scores candidates by **strike distance and expiration distance only**.
- Yet the lane's core sizing parameter is `wheel_delta = 0.25`, and there is a five-row `DELTA_TABLE` mapping delta to expected premium and assignment probability.

**Delta is never measured anywhere in Trezo.** The contract is chosen by percentage-OTM, and its delta is then *asserted* from the hardcoded table. That disconnect is the single most valuable thing this program can close, and it produces an extra question worth answering first: *what delta is a 5%-OTM 30-DTE put, actually, on these names?*

---

## 2. The target list

Every constant below drives live sizing today. File paths are given so Mike can place the results; **you are not editing these files.**

| # | Constant | File | Current | What its own comment says |
|---|---|---|---|---|
| 1 | `DELTA_TABLE` (5 rows × 3 fields) | `agents/app/strategies/dividend_lt.py:47` | see below | *"UNPROVEN pending live chain data. Replace with measured values"* |
| 2 | `PREM_RATE_AT_025` | `dividend_lt.py:33` | `0.0060` | *"monthly premium at delta 0.25"* |
| 3 | `WHEEL_TR` | `dividend_lt.py:28` | `0.080` | *"UNPROVEN in this lane until measured … treat as optimistic"* |
| 4 | `LADDER_YIELD` | `dividend_lt.py:26` | `0.053` | *"blended screened bench"* |
| 5 | `LADDER_GROWTH` | `dividend_lt.py:27` | `0.045` | *"SCHD-class realized growth, discounted hard"* |
| 6 | `BUFFER_YIELD` | `dividend_lt.py:32` | `0.0375` | — |
| 7 | `block_cost` | `dividend_lt.py:74` | `3500.0` | *"100 × cheapest bench price"* — a default the agent never overrides |
| 8 | `RISK_FREE_RATE` | `agents/app/options/pricing.py:19` | `0.043` | *"~3-month T-bill territory. Configurable later."* |
| 9 | `MIN_QUALIFYING_YIELD` | `dividend_screen.py:79` | `0.015` | *"below this it is not a dividend name"* |

Current `DELTA_TABLE`:

```python
DELTA_TABLE = {
    0.15: {"prem_mo": 0.0040, "blended_tr": 0.084, "assign_prob": 0.15},
    0.20: {"prem_mo": 0.0052, "blended_tr": 0.088, "assign_prob": 0.20},
    0.25: {"prem_mo": 0.0060, "blended_tr": 0.090, "assign_prob": 0.25},
    0.30: {"prem_mo": 0.0075, "blended_tr": 0.095, "assign_prob": 0.30},
    0.40: {"prem_mo": 0.0105, "blended_tr": 0.105, "assign_prob": 0.40},
}
```

Note that `assign_prob` is currently set equal to delta in every row. That is the textbook rule of thumb, not a measurement. Testing it is E2.

**Hard guardrails you must respect when designing experiments** (Trezo refuses rather than clamps outside these):
`w_ladder ∈ [0.50, 0.90]` · `w_wheel ∈ [0.00, 0.40]` · `w_buffer ∈ [0.03, 0.20]` · `wheel_delta ∈ [0.15, 0.40]` · wheel DTE window `[5, 45]`.

---

## 3. The universes

Use exactly these. They are Trezo's real lists, so a measurement on anything else does not transfer.

**Wheel bench (22 names):**
```
O, MAIN, STAG, NLY, ARCC, F, T, KMI, VZ, MO, INTC,
PFE, KHC, CSCO, BMY, KEY, HPQ, AGNC, NOK, VALE, KGC, PSEC
```

**Dividend ladder pool (~62 names):**
```
PG, KO, PEP, MDLZ, CL, KMB, GIS, K, JNJ, ABBV, PFE, MRK, BMY, AMGN, GILD, LLY,
JPM, BAC, C, WFC, USB, PNC, TFC, SPG, O, AMT, PLD, WELL, VTR,
XOM, CVX, COP, PSX, VLO, MPC, NEE, DUK, SO, AEP, EXC, D,
MMM, CAT, DE, HON, GE, DOW, IBM, CSCO, INTC, ORCL, QCOM, TXN, T, VZ, TMUS,
SCHD, VYM, DVY, HDV, NOBL, JEPI, JEPQ, DGRO
```

**Window:** 2015-01-01 → 2026-08-01 unless an experiment says otherwise. That covers 2018Q4, 2020, and 2022 — three regimes where a wheel behaves very differently. Options history on QuantConnect starts January 2012 if you want more; some of these ETFs are younger (JEPI 2020, JEPQ 2022, DGRO 2014 — check inception and say so rather than silently truncating).

---

## 4. Setup

**Account:** QuantConnect free tier is sufficient for E1–E9. It gives unlimited backtests, a research node, every asset class at minute-to-daily resolution, options with Greeks/IV/OI back to 2012, and Morningstar fundamentals. It does **not** give live trading, paper trading, the REST API, the LEAN CLI, or tick/second resolution — none of which this program needs.

**If Mike has upgraded to a paid seat (~$10/mo), you additionally get the REST API, the LEAN CLI, and Object Store writes.** Use them only to move *your own computed outputs*, never source data.

**Working environment:** their web Research environment (Jupyter, `QuantBook`). If a QuantConnect MCP server is available to you, prefer it — Claude Code is an officially supported client, and it lets you create projects, push files, run backtests and read results without the browser.

**The one call that does most of the work:**

```python
qb = QuantBook()
eq  = qb.add_equity("KO", data_normalization_mode=DataNormalizationMode.RAW)
opt = qb.add_option(eq.symbol)
df  = qb.history(opt.symbol, datetime(2015,1,1), datetime(2026,8,1), flatten=True)
```

Returns **every contract on every trading day** — not just filter survivors — with `strike`, `expiry`, `right`, `close`, `volume`, `open_interest`, `implied_volatility`, and `greeks.delta / gamma / vega / theta / rho`. 4,000 underlyings. This is the backbone of E1, E2, E5 and E8.

Use `DataNormalizationMode.RAW` on the underlying. Adjusted prices will silently corrupt every strike-relative calculation in this program.

---

## 5. The experiments

Run in order. E1 and E2 are the ones that matter most; if you only do two, do those.

---

### E1 — What delta is Trezo actually selling, and what does it pay?

**Objective.** Two numbers, and they are separate questions.
(a) The realized delta of a **5%-OTM, ~30-DTE put**, per name and pooled — because that is what Trezo actually sells, regardless of what `wheel_delta` says.
(b) A measured `prem_mo` for each of the five delta buckets in `DELTA_TABLE`.

**Method.** Pure DataFrame work on the option universe history. No backtest.

1. Pull the universe history for the 22 wheel names over the window.
2. Keep puts only. Compute `dte = expiry − date`.
3. **For (a):** on each date, for each name, find the contract closest to `strike = 0.95 × underlying_close` with `dte` closest to 30. Record its `greeks.delta`. Report the distribution per name and pooled — median, IQR, 10th/90th percentile. This is the answer to "is 0.25 even the right number to be arguing about."
4. **For (b):** bucket every put by `|delta|` into the five table keys with a ±0.025 band, restricted to `dte ∈ [25, 45]`. Compute `premium_rate = close / strike`, then normalize to a 30-day month: `prem_mo = premium_rate × (30 / dte)`. Report median and IQR per bucket.

**Output.**

```
delta_bucket | n_obs | prem_mo_median | prem_mo_p25 | prem_mo_p75 | current_value
0.15         |       |                |             |             | 0.0040
0.20         |       |                |             |             | 0.0052
0.25         |       |                |             |             | 0.0060
0.30         |       |                |             |             | 0.0075
0.40         |       |                |             |             | 0.0105
```
Plus the (a) table: `ticker | n_obs | delta_median | delta_p10 | delta_p90`.

**Acceptance criteria.** `prem_mo` must increase monotonically with delta — if it doesn't, your bucketing or your DTE normalization is wrong. Any bucket with **n < 500** reports `UNVERIFIED`. Sanity-check two or three rows by hand against a real historical quote before trusting the table.

**Traps.** The Greeks in this dataset are **previous-day close** values computed by QuantConnect's forward-tree model, not exchange-published. That is correct for calibration and wrong for anything intraday — say so in the report. Also: REITs and BDCs in the bench (O, MAIN, STAG, NLY, ARCC, AGNC, PSEC) have materially different vol surfaces from the industrials; report them as a separate cohort as well as pooled, because Trezo's own screen treats REIT+BDC as one shared risk factor.

---

### E2 — Does assignment probability actually equal delta?

**Objective.** Replace the `assign_prob` column, which is currently just a copy of delta.

**Method — and read this part carefully, because the obvious approach is the wrong one.**

Do **not** measure this by backtesting and counting LEAN's assignments. LEAN's `DefaultOptionAssignmentModel` has **no ex-dividend logic whatsoever** — it only assigns within 4 days of expiry and more than 5% in the money, via a no-arbitrage test. The classic case of a short ITM call assigned the day before an ex-dividend date is not modelled at all. On a bench that is entirely dividend payers, a backtest-derived assignment rate is a guaranteed undercount.

Instead, measure it **from the data**, which sidesteps the model entirely:

1. For every put in the E1 buckets, record entry delta and expiry.
2. Look up the underlying's close on the expiry date.
3. `finished_itm = underlying_close < strike`.
4. `assign_prob[bucket] = mean(finished_itm)`.

This is the honest quantity: how often a contract entered at delta *d* finished in the money. It is not identical to assignment probability (American options can be assigned early, and not every ITM contract is exercised) but it is measured rather than assumed, and it bounds the real number from a known direction.

**Then, optionally, the second measurement — which is the more interesting one.** Run a wheel backtest and count LEAN's *simulated* assignments by entry delta. The **difference** between that and step 4 is a number nobody has: how much assignment risk lives specifically in the early-exercise behaviour that neither LEAN nor Trezo models. If you have time for one extra thing, make it this.

**Output.** `delta_bucket | n_obs | finished_itm_rate | current_assign_prob` plus, if run, `lean_simulated_assign_rate | gap`.

**Acceptance criteria.** `finished_itm_rate` should be broadly comparable to delta but is very likely to differ — that difference is the finding, not an error. If it comes back *exactly* equal to delta in every bucket, you have a bug. Under n < 500, report `UNVERIFIED`.

---

### E3 — What total return does the wheel actually produce?

**Objective.** Replace `WHEEL_TR = 0.080`, whose own comment says treat it as optimistic.

**Method.** A backtest, over the 22-name bench, 2015→2026.

- Sell cash-secured puts at 5% OTM, ~30 DTE, using `OptionStrategies.NakedPut(...)`.
- On assignment, write covered calls at 5% OTM, ~30 DTE, using `OptionStrategies.CoveredCall(...)`. Use the strategy constructors, not raw legs — that is what triggers the position-group margin model with the IBKR-calibrated formulas.
- `SetBrokerageModel(BrokerageName.InteractiveBrokersBrokerage)`.
- `SetTradeBuilder(TradeBuilder(FillGroupingMethod.FillToFill, FillMatchingMethod.FIFO))` — **required**, see traps.
- Run it three ways: at `wheel_delta` equivalents of 0.15, 0.25 and 0.40 (i.e. varying the OTM percentage until median entry delta matches, using E1's mapping), so the result is a curve rather than a point.

**Output.** For each configuration: annualized total return, max drawdown, Win Rate, Expectancy, Profit-Loss Ratio, assignment count, and — most importantly for this lane — the **dispersion of per-name outcomes**. Report the spread, not just the mean. That is what the lane exists to narrow.

**Acceptance criteria.** If the measured TR comes back above 8%, be suspicious and check the margin model and the fill assumptions before believing it; the BXM index's forty-year record says the net add from covered-call writing is low single digits. **If your number contradicts that, the burden is on the number.**

**Traps.** Short puts get **Reg-T naked margin**, not full `strike × 100` collateral. Trezo's lane rule 5 is a hard collateral reservation — deliberately stricter. So QuantConnect's available buying power will look more permissive than Trezo's book actually is, and a backtest that leans on margin will overstate capacity. Either write a custom `BuyingPowerModel` that reserves `strike × 100`, or size positions manually and state the assumption loudly.

---

### E4 — Ladder yield and growth

**Objective.** Replace `LADDER_YIELD = 0.053`, `LADDER_GROWTH = 0.045`, `BUFFER_YIELD = 0.0375`.

**Method.** No options needed. Use the free Morningstar fundamentals (point-in-time, 8,000 US equities back to 1998) and the Security Master's dividend and split series.

1. Over the ladder pool, at each month-end, take the names that would pass a basic income screen: yield ≥ 1.5%, payout ratio measurable and not distressed.
2. `LADDER_YIELD` = the median trailing yield of that screened set, averaged over the window.
3. `LADDER_GROWTH` = the median 5-year CAGR of dividends per share across the same set.
4. `BUFFER_YIELD` = measure separately — this is the cash/short-duration sleeve; use SGOV where it exists (inception 2020) and BIL or SHV before that, and **say which** rather than splicing silently.

**Output.** Three numbers with the distribution behind each, plus a year-by-year table so Mike can see the 2020 and 2022 behaviour rather than just an average across them.

**Acceptance criteria.** The screened-set yield should be visibly *lower* than a naive average of the pool — the pool contains JEPI and JEPQ, whose distribution rates are option-income, not dividends, and will drag a naive mean upward by several points. If your `LADDER_YIELD` comes out above 6%, check whether covered-call ETF distributions have contaminated it.

---

### E5 — The real block cost

**Objective.** Replace `block_cost = 3500.0`, described as "100 × cheapest bench price" and never overridden at runtime. It drives `csp_blocks` and the U1/U2 capacity unlocks, so a wrong value mis-sizes the whole wheel sleeve.

**Method.** Trivial once E1's data is loaded. For each month in the window, across the 22-name bench, find the 5%-OTM 30-DTE put on the *cheapest* qualifying name and compute `strike × 100`. Report the time series, its median, and its range.

**Output.** `block_cost_median`, `block_cost_min`, `block_cost_max`, plus the monthly series. Note explicitly whether 3500 was ever right and when it stopped being right.

---

### E6 — What the hardcoded risk-free rate costs

**Objective.** Establish whether `RISK_FREE_RATE = 0.043` matters at Trezo's DTEs, so Mike can either fix it or stop thinking about it.

**Method.** Price a representative sample of the E1 contracts three ways and compare the resulting deltas:
- `ConstantRiskFreeRateInterestRateModel(0.043)` — Trezo's current assumption
- `InterestRateProvider()` — LEAN's dated default
- A curve model wired to the free US Treasury Yield Curve dataset

**Output.** Median and 90th-percentile absolute delta difference, broken out by year. One sentence of verdict: does a flat 4.3% move the selected strike, or not?

**Trap worth stating in the report.** LEAN's default `InterestRateProvider` is the **Fed discount-window primary credit rate**, not a T-bill yield — it typically sits ~50bp above the funds upper target. Better than a constant, not textbook. The Treasury curve is the right comparator.

---

### E7 — The benchmark the lane has never been measured against

**Objective.** Build the §7 rail: total return vs **50% SPY / 50% SGOV**. This rail is specified in Trezo's dividend spec and has never been built.

**Method.** Straightforward. Construct the benchmark, run the E3 and E4 strategies against it, report rolling excess return and — again — dispersion.

**Note the inception problem:** SGOV launched in 2020. Use BIL or SHV for the earlier period and label the splice explicitly in the output. Do not paper over it.

---

### E8 — Is there a liquidity floor worth having?

**Objective.** Trezo's `LiveOption` carries only OCC, strike, expiration and premium — **no open interest, no bid/ask spread**. It has no liquidity signal at all on the contracts it writes. Establish whether that costs anything.

**Method.** From the E1 dataset, bucket contracts by open interest (e.g. <100, 100–500, 500–2000, >2000) and compare realized premium rate and bid/ask spread where available. Then ask the actual question: **at what open-interest floor would Trezo have been excluded from contracts it currently writes, and what would that have cost or saved?**

**Output.** A recommended floor with the evidence, or an honest "no measurable effect at this bench's liquidity levels" — which is a perfectly good answer and probably the likelier one for names like O, T and VZ.

---

### E9 — How often does trailing yield mis-sort a name?

**Objective.** Trezo's screen gates on `MIN_QUALIFYING_YIELD = 0.015` using **trailing twelve-month** yield computed from broker corporate actions. The threshold was written for *indicated/forward* yield. These differ in a predictable, asymmetric way.

**Method.** Over the ladder pool, for each month, compute both trailing TTM yield and indicated forward yield (last regular dividend × frequency ÷ price). Count how often they land on opposite sides of 1.5%, and classify:
- **Recent initiators / raisers** — TTM understates, name wrongly excluded
- **Recent cutters** — TTM overstates, name wrongly admitted (this is the dangerous direction: the screen exists to exclude exactly these)
- **Special dividends** — inflate TTM on cash that will not repeat

**Output.** Mis-sort rate in each direction, with named examples. This tells Mike whether the trailing-yield gate is a real problem or a theoretical one.

---

## 6. The traps, consolidated

Any one of these silently produces a confident wrong number.

1. **Universe Greeks are previous-day close values** from QuantConnect's own forward-tree model, not exchange-published, and not customizable at filter time. Fine for calibration, wrong for anything intraday.
2. **MAE and MFE come back as zero** under the default flat-to-flat trade grouping. Set `FillToFill` or `FlatToReduced`.
3. **The assignment model has no ex-dividend logic.** See E2. This is the biggest trap in the program.
4. **Cash-secured put collateral is not modelled** — short puts get Reg-T naked margin. See E3.
5. **Use `DataNormalizationMode.RAW`.** Adjusted prices corrupt every strike-relative calculation here.
6. **No second-resolution or tick options data in backtests.** The new one-second OPRA feed is live-only; research and backtests top out at minute.
7. **Index options** (if you stray into SPX/NDX): live, QuantConnect does not carry the underlying index level at all; in backtests, their precomputed index-option Greeks **use SPY as a proxy for SPX and QQQ for NDX**.
8. **ETF distributions are not dividends.** JEPI, JEPQ and similar are in the ladder pool and pay option-income distributions. They will corrupt E4 if pooled naively.
9. **There is no moneyness selector and no contract-count cap** in the universe filter API. Both are done inside a custom contracts lambda.
10. **Inception dates.** SGOV 2020, JEPI 2020, JEPQ 2022, DGRO 2014. Truncate honestly and label it.

---

## 7. What to hand back

One markdown report. Structure:

**Part 1 — The constants table.** For each of the nine targets: current value, measured value, sample size, confidence, and a one-line note. Anything under-sampled reads `UNVERIFIED` with the count. Do not fill a gap with an interpolation.

**Part 2 — The findings that aren't constants.** The realized delta of a 5%-OTM put (E1a). The assignment gap (E2). The mis-sort rate (E9). These change how Mike thinks, not just what a variable equals.

**Part 3 — Dispersion, everywhere.** For every number, the spread alongside the central value. Restating the invariant: this lane's job is a narrower spread, not a higher mean. A measurement that reports only a mean is half-reported.

**Part 4 — What you couldn't measure and why.** Explicitly. This is as valuable as Part 1.

**Part 5 — Your notebooks**, so the work is reproducible. Code only — no embedded data extracts.

---

## 8. Do not

- Do not modify, patch, or propose edits to any Trezo file.
- Do not export raw bars, quotes, or chain data out of QuantConnect. Derived measurements only. If an output starts to resemble a reconstruction of their dataset, stop.
- Do not place any order, or deploy any live algorithm.
- Do not smooth, interpolate, or round a number toward the value it is replacing. If a measurement contradicts the placeholder, that is the entire point.
- Do not recommend raising the lane's expected return. The invariant in §1 is not negotiable.
- Do not treat a green backtest as evidence that a control binds. A separate audit of Trezo found that its dominant defect class is *built but not bound* — checks that exist, are tested, and never fire because the caller passes them nothing. Measurement work and binding work are independent, and a good number from this program says nothing about whether Trezo's guards are live.

---

## Appendix A — QuantConnect reference

**Cost.** Free tier covers everything in this program. Paid seat ~$10/mo adds the REST API, LEAN CLI and Object Store writes; ~$34/mo adds a live node and the live OPRA feed. Verify current pricing at quantconnect.com/pricing — a third-party review quotes $60/mo for "Researcher" against $10/$84 figures in QuantConnect's own pricing payload, and the discrepancy is unresolved.

**Data depth.** Equity and index options from January 2012, minute/hour/daily, 4,000 underlyings, AlgoSeek. Daily Greeks + IV + open interest via the US Equity Option Universe dataset, same start. Equities from 1998. Morningstar fundamentals free on every tier, point-in-time, 8,000 names from 1998.

**Free datasets relevant later:** Upcoming Earnings (EODHD, 97.3% exact-date), Upcoming Dividends (98.6% coverage), US Equity Security Master, US Equities Short Availability + borrow cost, FRED, US Treasury Yield Curve, CFTC Commitments of Traders, Fama-French.

**Universe filter API** (for reference — `OptionFilterUniverse`, all chainable):
`delta(min,max)` · `implied_volatility(min,max)` · `gamma` · `vega` · `theta` · `rho` · `open_interest(min,max)` · `strikes(min,max)` · `expiration(minDays,maxDays)` · `puts_only()` · `calls_only()` · `standards_only()` · `weeklys_only()` · `front_month()` · `contracts(selector)`

**Pricing models:** `OptionPriceModels.BlackScholes()`, `.BinomialCoxRossRubinstein()`, `.ForwardTree()`, plus twelve legacy models under `OptionPriceModels.QuantLib.*` including `BaroneAdesiWhaley()` and `BjerksundStensland()` for American exercise. Default is Cox-Ross-Rubinstein for American, Black-Scholes for European. Greeks are dividend-aware by default via `DividendYieldProvider`.

---

## Appendix B — Mike's own lane (~30 minutes, no agent needed)

Mike, if you want to poke at this yourself before or alongside the agent work:

1. **Sign up free at quantconnect.com.** No card. You get unlimited backtests and a research node.
2. **Open a research notebook** and paste the four lines from §4 with `"O"` as the ticker. What comes back is every option contract on Realty Income, every day since 2012, with delta and IV attached. That single DataFrame is the thing this whole program is built on — worth seeing it land before deciding whether any of it is worth doing.
3. **Then try one thing:** filter it to puts, ~30 DTE, strike ≈ 95% of spot, and look at the delta column. That number is what your Wheel has actually been selling all along. My guess is it is nowhere near 0.25, and it varies a lot by name — but that is a guess, which is exactly the problem this program exists to fix.
4. **If you want the agent to drive it instead**, connect QuantConnect's MCP server — Claude Code is an officially supported client, so the agent can create the project, run the backtest and read results without you opening their IDE.

---

*Prepared from a direct read of Trezo at commit `229b1ee` and QuantConnect's own documentation, pricing data, and the 26 August 2026 options-feed announcement. Trezo constants and universes above are verbatim from source, not from memory.*
