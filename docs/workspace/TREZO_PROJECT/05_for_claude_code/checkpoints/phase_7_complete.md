# Phase 7 — Tax Optimizer — COMPLETE

> Built by Nova, 2026-05-20. Grounded in sources Mike provided: the IRS
> "One Big Beautiful Bill provisions" page (P.L. 119-21), IRS publications,
> and Fidelity crypto-tax guidance.

## What shipped

### Tax engine (`web/src/lib/tax.ts`)
- 2025 federal ordinary-income brackets for all four filing statuses, plus
  standard deductions and long-term capital-gains 0/15/20% ceilings.
- `holdingTerm()` — short vs long term from entry/exit dates (≥365 days = long).
- `summarizeGains()` — splits realized P&L into short-term / long-term, counts
  winners and losers. Works on crypto positions too (crypto = property).
- `detectWashSales()` — flags a loss when the same ticker was (re)bought within
  30 days. Simplified planning scan, not a legal determination.
- `estimateTax()` — short-term gains stack on ordinary income (marginal-cost
  method); long-term gains taxed through the 0/15/20% ladder; flat state rate
  applied on top. Returns federal, state, combined, and effective rate.
- `quarterlyEstimates()` — splits closed positions into IRS quarters and
  estimates each quarter's payment.

### Database (`db/migrations/0011_tax_fields.sql`)
- `profiles.annual_income_usd` and `profiles.state_tax_rate_pct` added so the
  estimate knows the user's marginal bracket and home-state rate.

### Web UI
- **`/dashboard/tax`** — full tax-position page: 4 KPI tiles (realized YTD,
  short-term, long-term, estimated tax), estimate breakdown, quarterly
  estimated-payment table, wash-sale flags, full realized-trades ledger.
  Prominent amber "estimate, not tax advice" disclaimer at the top.
- **`/api/tax/export`** — Schedule-D / Form-8949-style CSV download
  (description, acquired, sold, proceeds, cost basis, gain/loss, term).
- Profile settings page already lets the user edit income + state rate.

### Tax Optimizer Agent (`agents/app/agents/tax_optimizer.py`)
- Was a heartbeat stub. Now a real agent: every 30 minutes it reads each
  user's YTD realized P&L and emits a tax-position summary with an estimated
  setaside (~22% blended default, since most paper trades close same-day and
  are short-term). The detailed bracket math stays in the web app.

### Nav
- "Tax Optimizer" enabled in the Settings sidebar group → `/dashboard/tax`.

## On the One Big Beautiful Bill (the PDF Mike provided)

I read the full IRS OBBB provisions page. Findings:
- **OBBB did NOT change capital-gains math.** It made the TCJA individual
  brackets permanent (they were set to sunset end of 2025). The 0/15/20%
  long-term rates, wash-sale rules, and crypto-as-property treatment are all
  unchanged. The Phase 7 bracket structure is current.
- **The OBBB provision that matters most for Trezo is Trump Accounts
  (Section 70204)** — new federal tax-advantaged child accounts: $1,000
  government seed, $5,000/yr contributions, must invest in U.S. index ETFs,
  locked until age 18, then IRA-like. This is the natural account vehicle for
  **Phase 8 KINDRIP**. Saved to memory (`project_trump_accounts_kindrip.md`)
  so Phase 8 uses it.
- Crypto: still taxed as property → capital gains, same rates as stocks.
  Brokers (e.g. Coinbase) issue the new **Form 1099-DA** for digital assets
  starting tax year 2025. Trezo isn't a broker, so it doesn't issue 1099-DAs —
  but the tax ledger already includes crypto positions in the gain/loss math.

## Decisions made (worth remembering)

1. **Estimator, not filer.** Every number is labeled an estimate; the page
   leads with a "not tax advice — hand this to a CPA" disclaimer. Brackets are
   approximate and will need a yearly refresh.
2. **Tax math lives in the web app**, not the agent. The agent gives the
   running "set aside ~$X" nudge; the page does the precise brackets. One
   source of truth, rendered where the user looks.
3. **Short-term marginal-cost method.** ST gains are taxed as the *difference*
   between tax(income + STgains) and tax(income) — the honest marginal cost,
   not a flat rate.
4. **State tax is a single user-entered rate.** Encoding 50 states' brackets
   is out of scope; one effective rate keeps the estimate honest and simple.
5. **Almost everything is short-term** because paper trades close fast (STMS
   same-day, crypto SCALP in minutes). The engine still classifies correctly
   for when longer holds appear.

## Exit criteria status

| Criterion | Status |
|---|---|
| Every trade contributes to the tax ledger | ✅ all closed positions feed the engine |
| User can see YTD realized gains/losses | ✅ /dashboard/tax KPIs + ledger |
| Quarterly estimates calculated | ✅ quarterly table |
| Export matches IRS format | ✅ Schedule-D / 8949-style CSV |

## What the user needs to do

1. **Apply migration** `db/migrations/0011_tax_fields.sql` in Supabase.
2. **Restart agents** (`nuke-agent-cache.bat`) — Tax Optimizer is now a real
   ticking agent. Bootstrap still shows `count=11`.
3. **Restart web** (`start-web.bat`).
4. Hard-refresh. In **Settings → Profile**, set your annual income and state
   tax rate (0 if your state has no income tax) for an accurate estimate.
5. Open **Settings → Tax Optimizer** (`/dashboard/tax`). Once you've closed
   some paper trades, the page shows realized gains, the tax estimate, and the
   quarterly breakdown. The "Export Schedule D CSV" button downloads a
   CPA-ready file.

## Known limitations / open items

- Brackets are 2025 approximations — need a yearly update, ideally pulled from
  an IRS source rather than hardcoded.
- Wash-sale scan is simplified (same-ticker, 30-day window) — doesn't cover
  options, "substantially identical" securities, or cross-account rules.
- No Trader Tax Status (TTS) / 475(f) mark-to-market election handling — the
  founder's `TREZO_TAX_STRATEGIES.md` mentions these; they're advanced and
  deferred.
- Self-employment tax not modeled (Trezo trading gains are capital gains, not
  SE income, so this is correct for now).

## Next phase options

- **Phase 8: KINDRIP** — child portfolios, now with Trump Accounts as the
  recommended vehicle (see memory note). The innermost protection ring.
- **Phase 6d/6e** — Dividend Wheel + Options strategies (need an options feed).
- **Phase 5b** — per-user agent runtime (should land before real money).
