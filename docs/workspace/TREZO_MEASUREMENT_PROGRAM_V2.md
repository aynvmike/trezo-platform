# Trezo Measurement Program v2 — Generalized

**Supersedes** `TREZO_QC_MEASUREMENT_PROGRAM.md` (the QuantConnect handoff brief).
Author: Nova · For: Mike · Date: 2026-08-29 · Status: rails verified by live probe, ready to execute

---

## 0. Why v2 exists

v1 was written around QuantConnect's LEAN data. Mike cannot use the LEAN CLI / API
without a registered business account, so v2 rebuilds the same nine experiments on
**rails Trezo already holds** — the Alpaca keys the platform trades with every day,
the public Treasury feed, and the container's own Python. No new account, no new
vendor, no CLI.

Everything below marked **PROBED** was verified live on 2026-08-29 from the Cowork
container using the existing Alpaca paper keys. This is not a plan that hopes the
data exists; the calls were made.

The program's character is unchanged and its rules carry over verbatim (§6):
measurement, not build; UNVERIFIED beats a guess; dispersion beside every mean;
never propose raising the dividend lane's expected return.

One scope change from v1: v1 forbade touching Trezo because a QC-side agent had no
business in the repo. v2 is executed by Nova, who maintains Trezo — so the *report*
still only hands back values with evidence and Mike still decides what lands in
code, but v2 may **add** capture instrumentation (E10) as a normal reviewed change.

---

## 1. Verified capability matrix

| Rail | Probe result (2026-08-29) | Serves |
|---|---|---|
| Alpaca option **daily bars**, expired contracts included | **PROBED** — `KO250117P00060000` returned 10 bars Nov-2024; earliest confirmed **Feb 2024** (`KO240315P00057500`, 5 bars Feb-2024). OHLC+volume+trade count. No greeks, no IV. | E1, E2, E3 (short window), E5, E8 |
| Alpaca option **contracts listing**, `status=inactive` | **PROBED** — expired July-2024 KO puts listable. Historical chains reconstructable per date. Carries current **open_interest** (daily) + last close. | E1 candidate selection, E8 |
| Alpaca **stock daily bars**, `feed=sip` | **PROBED** — KO from **June 2016**; 2015 empty. Raw (unadjusted) available, which strike-relative math requires. | E2 outcomes, E4, E5, E7, E9 |
| Alpaca **corporate actions** (cash dividends, `special` flag, ex-dates) | **PROBED** — KO 2016 returns 4 dividends with rates; 2025 full detail. | E4, E9 |
| **Treasury.gov** daily yield curve CSV | **PROBED** from the container — full curve, 2016 file confirmed, decades of history, no key needed. (FRED is egress-blocked; not needed.) | E6, greeks input |
| **Computed greeks** — our own Black-Scholes w/ continuous dividend yield, IV solved from close premium, Treasury 1-Mo rate | **PROBED** — E1a pilot ran end-to-end (below). Cross-check model: CRR binomial for American exercise. | E1, E2, E6 |
| Webull MCP (chains via `get_option_data`, fundamentals, dividend calendar), IBKR MCP, LSEG skills, Daloopa/S&P | Wired in Cowork, depth unprobed — use for spot-checks and **current** payout ratios / forward yields, not bulk history. | E4 screen, E9 cross-check |
| yfinance from the container | **BLOCKED** (Yahoo not on the egress allowlist). Runs on the Trezo server if ever needed; not required — Alpaca covers it. | — |
| QuantConnect **free web tier** (browser research notebooks, no CLI, no API) | Not required for v2. Kept as an optional cross-check lane (§5). Verify signup terms first — the CLI/API experience suggests their account tiers shifted. | E3 full-window cross-check |

**The one real gap:** options history **before Feb 2024**. Nothing wired reaches it.
Consequence per experiment is stated inline; acquisition options in §5.

---

## 2. Pilot already run — the pipeline is real

E1a executed in miniature on 2026-08-29 (`ops/measure/e1a_pilot.py`): 8 sample
dates 2024-03 → 2026-07, 5%-OTM nearest-30-DTE put, IV solved from the close,
delta from that IV.

```
KO  n=8  |delta| median 0.188   range [0.112, 0.211]   DELTA_TABLE asserts 0.25
O   n=2  |delta| median ~0.24   (45-DTE only; listing gaps to fix in full run)
```

Two things v1 predicted, visible already: the 5%-OTM put is **nowhere near 0.25
delta** on a low-vol staple (KO sold 0.11–0.13 delta through early 2024 — near-
lottery premiums), and the REIT cohort runs meaningfully richer. n=8 is
**UNVERIFIED** by the program's own standard — this is a pipeline proof and a
preview, not a result. The full run pools every trading day × 22 names.

Greeks caveat, stated once and repeated in every report: our greeks are
**model-derived from daily closes** (BS + dividend yield + Treasury rate), not
exchange-published — the same caveat class as QC's forward-tree previous-close
greeks. Correct for calibration; wrong for anything intraday. Daily option bars on
low-volume contracts can close stale; the full run filters `n_trades ≥ 3` per bar
and reports how many observations that drops.

---

## 3. The experiments, remapped

Targets, universes, guardrails, acceptance criteria and traps are **unchanged from
v1** (§2, §3, §6 there) — only the rails change. Status legend:
**READY-FULL** = full 2016→2026 window in-house · **READY-2024+** = in-house, window
Feb 2024→now · **HYBRID** = in-house + labeled model or optional external lane.

- **E1 — realized delta + prem_mo by bucket. READY-2024+.**
  Chains reconstructed per date from `status=inactive` listings (fallback where a
  listing gap appears, as with O: generate candidate OCC symbols from the strike
  grid and keep those with bars). Window caveat: Feb 2024→now misses 2018Q4/2020/
  2022; the 2024-08 and 2025 drawdowns are in-window. Report per-name, pooled, and
  REIT/BDC cohort separately, exactly as v1 specifies.

- **E2 — does assign_prob equal delta? READY-2024+.**
  Entry delta from E1's computed greeks; `finished_itm` from SIP close on expiry
  date. No assignment model involved — v1's central trap (LEAN's missing
  ex-dividend logic) disappears entirely because no simulator is used. The optional
  LEAN-gap measurement from v1 is dropped; the early-exercise premium gap is
  instead bounded qualitatively (flag ITM-at-ex-date cases using corporate-actions
  ex-dates — we have them).

- **E3 — wheel total return. HYBRID, the honest weak spot.**
  (a) READY-2024+: an in-house event replay over real option bars — sell the E1
  contract, roll/assign by rules, collateral reserved at full `strike × 100`
  (Trezo's rule 5 — stricter than any margin model, stated loudly). ~2.6 years
  only. (b) Full-window shape check 2016→2026: same replay with **synthetic**
  BS-priced premiums from SIP underlying + Treasury rates — labeled MODELED,
  usable for regime shape, never for the level. (c) Optional: QC free web-tier
  backtest as cross-check (§5). v1's acceptance stands: a number above 8% carries
  the burden of proof.

- **E4 — ladder yield & growth. READY-FULL (2016→2026).**
  Corporate-actions dividends + SIP prices over the 62-name pool. TTM yield
  monthly; growth = 5-yr dividend CAGR (2021+ measurements use in-window history;
  earlier years labeled shorter-lookback rather than silently truncated).
  Payout-ratio screen: historical point-in-time EPS is NOT wired — run the yield
  screen historically, apply the payout screen only at today's snapshot (Webull/
  Daloopa), and say so. v1's JEPI/JEPQ contamination trap stands: option-income
  distributions are excluded from `LADDER_YIELD`, reported separately.
  `BUFFER_YIELD`: SGOV distributions 2020→, BIL before, splice labeled.

- **E5 — real block cost. READY-FULL.**
  `block_cost ≈ strike×100 ≈ 0.95 × cheapest-qualifying-name price × 100` needs
  only equity closes — monthly series 2016→2026 from SIP bars; exact
  strike-grid version 2024+ from real chains. Both reported.

- **E6 — risk-free-rate sensitivity. READY-FULL.**
  Reprice the E1 sample three ways: flat 0.043 (Trezo today), Treasury 1-Mo, and
  Treasury curve-interpolated at each contract's DTE. Delta difference by year.
  v1's comparator problem (LEAN's discount-window rate) vanishes — we go straight
  to the Treasury curve.

- **E7 — the 50% SPY / 50% SGOV rail. READY-FULL.**
  Total-return from SIP bars + dividend reinvestment via corporate actions
  (self-computed adjustment — state the method; Alpaca raw bars + our own
  reinvestment beats trusting a vendor's adjusted series we can't inspect).
  SGOV/BIL splice labeled, per v1.

- **E8 — liquidity floor. READY-2024+ (volume), forward (OI/spread).**
  Historical: per-contract daily volume + trade count from option bars. OI is
  current-only on the contracts endpoint and historical quotes returned 404 on
  our feed — so the OI/spread half of E8 is built **forward** by E10's recorder.
  Report volume-bucket findings now; OI floor after ~60 recorder days.

- **E9 — TTM vs forward yield mis-sorts. READY-FULL.**
  Corporate actions carry rate, ex-date, and the `special` flag — TTM and
  indicated-forward yields both computable per month 2016→2026, mis-sorts
  classified exactly as v1 specifies (cutters = the dangerous direction).

- **E10 — NEW: the forward chain recorder (platform improvement).**
  A small nightly job (cloud scheduled task, existing keys) records, per bench
  name: the 5%-OTM/30-DTE put's OCC, close, computed IV/delta, **open interest**,
  and quote spread from the snapshot endpoint — derived rows only, ~22/night,
  into `reports/` (and optionally Supabase). In 60–90 days Trezo owns the
  dataset no free source sells: its own liquidity and delta history, measured at
  the exact contracts it would write. This is the "make the platform better every
  day" piece — proposed as a normal reviewed change, not run unilaterally.

---

## 4. Execution order

1. **Session 1:** E1 full run (22 names, Feb 2024→now, all trading days) + E2 off
   the same dataset + E5. These produce the constants table's biggest rows.
2. **Session 2:** E4 + E9 + E7 (pure equity/dividend work, full window) + E6.
3. **Session 3:** E3(a) replay + E3(b) modeled shape check; E8 volume buckets.
4. **Standing:** E10 recorder (after Mike approves it), 1 PM-report-style
   scheduled task; first OI-floor read after ~60 days.

API budget note: the full E1 run is ~640 trading days × 22 names of bar queries —
batched by contract (one call per contract's whole life, not per day), it is a few
thousand calls; run at a polite rate off-hours, cached to disk in the container so
re-runs are free.

## 5. If a gap must be bought (only if Mike wants pre-2024 options truth)

- **QuantConnect free web tier** — browser notebooks; v1 said free tier needs no
  CLI/API and covers E1–E9 with 2012+ options data. Given the business-account
  wall Mike hit on the CLI, verify what a free personal signup actually grants
  before planning on it. Cost: $0 to find out. Their data stays in their lab;
  derived numbers only come home (v1 §0 rule 3 applies in full there).
- **Commercial options history** (ThetaData, Polygon.io options plans, and
  similar): years of history including greeks for tens of dollars a month —
  pricing changes often, verify on their sites at decision time. Only worth it if
  the 2024+ window proves too regime-thin AND the QC lane stays walled.
- **Do not** buy anything to replace E4–E9 — they are fully in-house.

## 6. Rules carried over verbatim from v1

- A bucket under n=500 reports **UNVERIFIED**, never an interpolation.
- Dispersion beside every central value — the dividend lane's job is a narrower
  spread, not a higher mean; never recommend raising its expected return.
- Do not smooth a measurement toward the placeholder it replaces.
- Raw data is never redistributed — derived measurements only (now an internal
  house rule; Alpaca data is used under Mike's own brokerage data terms).
- A green backtest is not evidence a control binds. Measurement work and binding
  work are independent.
- Hand-back format: v1 §7 — constants table with confidence, findings that aren't
  constants, dispersion everywhere, what couldn't be measured and why,
  reproducible code with no embedded data extracts.

---

*Probes and pilot executed 2026-08-29 from the Cowork container with Trezo's
existing Alpaca paper keys; pilot code at `ops/measure/e1a_pilot.py`. Constants,
universes, guardrails and traps referenced from v1, which remains the reference
for experiment-level detail.*
