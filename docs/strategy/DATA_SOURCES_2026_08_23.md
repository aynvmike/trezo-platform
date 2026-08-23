# Data sources — what each one actually answers
### 2026-08-23. Every row below was probed live, not read off a pricing page.

Mike: *"verify where we can get all information from a single source, and
then find ways to cover the missed data."*

**Answer: two sources, not six.** Alpaca answers everything about the
market and about corporate actions. Finnhub answers company fundamentals.
Three keys in `.env` answer nothing at all and should be retired.

---

## 1. The verdict

| what the platform needs | source | status |
|---|---|---|
| bars / prices, historical + live | **Alpaca** | ✅ incl. `adjustment=all` for total return |
| market movers, most-actives | **Alpaca** | ✅ |
| crypto bars + trading | **Alpaca** / Kraken | ✅ |
| option chains, quotes | **Alpaca** | ✅ `/v1beta1/options/snapshots` |
| **dividend payments + ex-dates** | **Alpaca** | ✅ `/v1/corporate-actions`, back to 2016 |
| **ETF / fund distributions** | **Alpaca** | ✅ same endpoint — this is the ETF fix |
| corporate actions (splits etc.) | **Alpaca** | ✅ |
| payout ratio, sector, market cap | **Finnhub** | ✅ stocks only |
| earnings calendar | **Finnhub** | ✅ `/calendar/earnings`, 60/min |
| option Greeks | *computed locally* | ⚠️ not in Alpaca snapshots; `wheel.py` models them (Black-Scholes) |
| forex | Kraken | ➖ lane dormant by design |

### Retire these three

| key | probe result |
|---|---|
| `TWELVE_DATA_API_KEY` | `/dividends`, `/earnings`, `/statistics` all **403 — paid plans only**. Nothing usable on this tier. |
| `NASDAQ_DATA_LINK_API_KEY` | **403** on the WIKI dataset. Discontinued years ago. |
| `ALPHA_VANTAGE_API_KEY` | `EARNINGS_CALENDAR` works, but at **25 calls/day** vs Finnhub's 60/**minute** for the same data. Keep as a cold backup; use it for nothing. |

---

## 2. The gap that started this

Finnhub's `/stock/dividend` — the payment series — is **not on this
tier**: *"You don't have access to this resource."* That single missing
endpoint caused both earlier failures:

1. The screen marked raise-streak and cut-history UNVERIFIED, refused to
   pass a name on unverified evidence, and therefore **admitted nothing
   at all** — while looking exactly like a strict gate working.
2. The substitute (`dividendGrowthRate5Y`) **inverted the rule**: a
   company that cut to zero and restarted shows a huge CAGR off a
   near-zero base, so TMUS (+124%) and Ford (+38%) ranked at the *top* of
   a ladder whose screen exists to exclude them.

Alpaca's corporate-actions feed answers it properly and for free:
`ex_date`, `record_date`, `payable_date`, `rate`, `special` — 2016 to
present, **including ETFs**, which Finnhub's fundamentals do not cover at
all (`profile2` returns `{}` for SCHD).

---

## 3. Three real defects the switch exposed

**a. The ex-date guard had never fired.** `options_scanner` passed
`ex_date=getattr(leg, "ex_date", None)` — and `leg` carries no such
attribute, so it was `None` on every single call. Lane rule 3, the rule
that stops a covered call losing its dividend to early exercise, was live
and structurally silent. Same for `tier`, which made lane rule 4 (GROWTH
names never wear a call) equally inert. Both now read from real sources.

**b. A 10-year streak was not expressible.** Alpaca's history starts in
2016, so ten complete years yield at most **nine** year-over-year
comparisons. A literal `>= 10` rejected every company on earth. The rule
is now *"unbroken across everything visible, up to the 10-year target"* —
honest today, and it tightens on its own as history accumulates.

**c. Monthly payers were being failed by the calendar.** Realty Income
raised its dividend every year 2016→2023 and scored a **streak of zero**.
Cause: 2024 recorded 11 payments and 2025 recorded 13 — one monthly
payment slipped across a year boundary, understating one year and
overstating the next. Dropping short years did not help; that leaves a
*gap* in the sequence and a consecutive-year streak breaks anyway. Years
near the norm are now **normalised** to the modal payment count (a timing
shift corrected, not a dividend change); years far off are left raw,
because that is a genuinely suspended payout the cut rule should see.

O now passes with a 9-year streak, which is what it has.

---

## 4. What the screen says now

Same 15 names, live data, single source:

```
PASS   JNJ  KO  PG  MRK  AMGN     GROWTH,  9-year unbroken streak
PASS   O                          HIGH_YIELD, 5.70% — the Aristocrat, correctly admitted
PASS   VYM  DGRO                  funds, yield from ACTUAL distributions
FAIL   SCHD                       distributions cut inside the record (2.45 -> 1.05, same 4 payments)
FAIL   MAIN T  NLY  F             cut inside the 10-year record
FAIL   TMUS                       2-year streak on a 4-year record — too new to judge
FAIL   ABBV                       payout ratio 276%
```

8 of 15 admitted. Discriminating, not blocking — which is the difference
between a gate and a wall.

---

## 5. Remaining gaps, named honestly

- **Option Greeks.** Alpaca snapshots return quotes and bars, no Greeks
  or IV. `wheel.py` computes its own via Black-Scholes, which is fine for
  strike selection but means delta is *modelled*, not observed. Worth
  knowing when the advisor's delta cap is doing work.
- **Point-in-time fundamentals.** Nobody on this stack offers them, so
  any backtest that screens on today's data carries lookahead bias. This
  is why the 3-month replay is an anecdote, not evidence.
- **Payout ratio for funds.** Genuinely inapplicable rather than missing.
  A fund with a verified decade of distributions is judged on that
  record; the earnings payout ratio is marked `n/a`, not failed.

*— Nova, for Mike. Every claim here came from a live probe on 2026-08-23.*
